#!/usr/bin/env python3
"""
export_grants.py — Export quality-assured grant records from the Stage 3
PostgreSQL database to data/grants.json for the static searchable interface.

INCLUSION RULE:
  (review_status = 'approved')
  OR (requires_review = false AND review_status = 'pending')

  Excluded: review_status = 'rejected',
            and requires_review = true AND review_status = 'pending'.

By default current_status = 'Closed' records are also excluded.
Use --include-closed to override.

Usage:
    python export_grants.py
    python export_grants.py --include-closed
    python export_grants.py --output /path/to/custom.json
"""

from __future__ import annotations

import argparse
import datetime
import decimal
import html
import json
import os
import sys
import uuid
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import psycopg2
from psycopg2.extras import RealDictCursor

# ---------------------------------------------------------------------------
# python-dotenv is optional but preferred; fall back to os.environ gracefully.
# ---------------------------------------------------------------------------
try:
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:
    pass  # dotenv not installed — rely on environment variables already set

# ---------------------------------------------------------------------------
# Default paths (relative to this file's location)
# ---------------------------------------------------------------------------

_SCRIPT_DIR = Path(__file__).parent
_DEFAULT_OUTPUT = _SCRIPT_DIR / "data" / "grants.json"

# ---------------------------------------------------------------------------
# Columns to export (JSONB audit columns are intentionally omitted)
# ---------------------------------------------------------------------------

_EXPORT_COLUMNS = """
    id,
    grant_title,
    funder_name,
    source_url,
    application_portal_url,
    description,
    application_deadline,
    application_deadline_raw,
    application_deadline_type,
    deadline_notes,
    eoi_deadline,
    eoi_deadline_raw,
    grant_opening_date,
    funding_amount_min,
    funding_amount_max,
    currency,
    current_status,
    source_language,
    ai_focused,
    individuals_not_eligible,
    organisation_types,
    individual_eligibility,
    applicant_base_regions,
    applicant_base_countries,
    geographic_focus_regions,
    geographic_focus_countries,
    thematic_sectors,
    grant_types,
    domain,
    crawl_date
"""

# Columns whose DB value may be NULL but must serialise as [] in JSON
_ARRAY_COLUMNS: frozenset[str] = frozenset(
    {
        "organisation_types",
        "individual_eligibility",
        "applicant_base_regions",
        "applicant_base_countries",
        "geographic_focus_regions",
        "geographic_focus_countries",
        "thematic_sectors",
        "grant_types",
    }
)

# ---------------------------------------------------------------------------
# SQL query (built dynamically to optionally exclude Closed)
# ---------------------------------------------------------------------------


def _build_query(include_closed: bool) -> str:
    closed_clause = (
        ""
        if include_closed
        else "    AND (current_status IS DISTINCT FROM 'Closed')\n"
    )
    return f"""
SELECT
{_EXPORT_COLUMNS}
FROM grants g
WHERE
    (
        g.review_status = 'approved'
        OR (g.requires_review = false AND g.review_status = 'pending')
    )
{closed_clause}
    -- English-only: source_language is stored as ISO 639-1 codes ("en", "fr",
    -- "nl", "de", …) but may have trailing whitespace — use TRIM().
    -- Keep "en", NULL (language not detected — assume English),
    -- and "ot" (unrecognised code — safer to keep than silently drop).
    -- Exclude all other language codes (fr, nl, de, es, pt, …).
    AND (g.source_language IS NULL OR TRIM(g.source_language) IN ('en', 'ot'))

    -- Stale deadline filter: exclude any grant whose application deadline has
    -- already passed, regardless of current_status.  Grants without a fixed
    -- deadline (Rolling, TBC) have NULL application_deadline and are kept.
    AND (g.application_deadline IS NULL OR g.application_deadline >= CURRENT_DATE)

    -- Quality filter: exclude records that have no specific grant URL.
    -- A URL is considered "specific" only if it is unique among approved records
    -- (i.e. not a generic listing page or portal homepage shared by many grants).
    --
    -- Logic:
    --   1. If application_portal_url is set AND unique → keep (specific grant page)
    --   2. If application_portal_url is NULL AND source_url is unique → keep
    --      (source page was a dedicated single-grant page)
    --   3. Everything else → drop (generic portal homepage or listing page)
    AND (
        (
            g.application_portal_url IS NOT NULL
            AND (
                SELECT COUNT(*)
                FROM grants g2
                WHERE g2.application_portal_url = g.application_portal_url
                  AND (
                      g2.review_status = 'approved'
                      OR (g2.requires_review = false AND g2.review_status = 'pending')
                  )
            ) = 1
        )
        OR (
            g.application_portal_url IS NULL
            AND (
                SELECT COUNT(*)
                FROM grants g2
                WHERE g2.source_url = g.source_url
                  AND (
                      g2.review_status = 'approved'
                      OR (g2.requires_review = false AND g2.review_status = 'pending')
                  )
            ) = 1
        )
    )

ORDER BY
    -- API-sourced records always beat LLM-crawled records for the same grant.
    -- When deduplication iterates this list, the first record for a
    -- (title, deadline) pair wins — so api_* must come first.
    CASE WHEN g.domain LIKE 'api_%' THEN 0 ELSE 1 END,
    CASE g.current_status
        WHEN 'Open'     THEN 1
        WHEN 'Upcoming' THEN 2
        WHEN 'Rolling'  THEN 3
        WHEN 'Closed'   THEN 5
        ELSE                 4
    END,
    g.application_deadline ASC NULLS LAST
"""


# ---------------------------------------------------------------------------
# Acronym restoration
# ---------------------------------------------------------------------------
# The LLM often title-cases acronyms (e.g. "Msca" instead of "MSCA",
# "Dsti-Nrf" instead of "DSTI-NRF").  This list maps the incorrectly
# title-cased form to the correct all-caps form and is applied to
# grant_title and funder_name at export time.

import re as _re

_ACRONYM_FIXES: list[tuple[str, str]] = [
    # Funding bodies / programmes
    ("Msca",        "MSCA"),
    ("Twas",        "TWAS"),
    ("Unesco",      "UNESCO"),
    ("Unicef",      "UNICEF"),
    ("Undp",        "UNDP"),
    ("Unfccc",      "UNFCCC"),
    ("Unep",        "UNEP"),
    ("Nsf",         "NSF"),
    ("Nih",         "NIH"),
    ("Nasa",        "NASA"),
    ("Noaa",        "NOAA"),
    ("Dsti",        "DSTI"),
    ("Dsi",         "DSI"),
    ("Nrf",         "NRF"),
    ("Ahrc",        "AHRC"),
    ("Esrc",        "ESRC"),
    ("Epsrc",       "EPSRC"),
    ("Bbsrc",       "BBSRC"),
    ("Nerc",        "NERC"),
    ("Stfc",        "STFC"),
    ("Erc",         "ERC"),
    ("Eic",         "EIC"),
    ("Anr",         "ANR"),
    ("Nwo",         "NWO"),
    ("Dfg",         "DFG"),
    ("Fct",         "FCT"),
    ("Snsf",        "SNSF"),
    ("Fwo",         "FWO"),
    ("Bmbf",        "BMBF"),
    ("Daad",        "DAAD"),
    ("Cnrs",        "CNRS"),
    ("Ukri",        "UKRI"),
    ("Rcuk",        "RCUK"),
    ("Oecd",        "OECD"),
    ("Nato",        "NATO"),
    ("Asean",       "ASEAN"),
    ("Who",         "WHO"),
    ("Fao",         "FAO"),
    ("Wfp",         "WFP"),
    ("Iaea",        "IAEA"),
    ("Ifc",         "IFC"),
    ("Idb",         "IDB"),
    ("Adb",         "ADB"),
    ("Afdb",        "AfDB"),
    ("Ebrd",        "EBRD"),
    ("Eib",         "EIB"),
    ("Giz",         "GIZ"),
    ("Usaid",       "USAID"),
    ("Fcdo",        "FCDO"),
    ("Dfid",        "DFID"),
    ("Norad",       "NORAD"),
    ("Sida",        "Sida"),   # Sida is the official capitalisation
    ("Jica",        "JICA"),
    ("Koica",       "KOICA"),
    ("Apctt",       "APCTT"),
    ("Twas-Cui",    "TWAS-CUI"),
    # Domain / field abbreviations
    ("Ai",          "AI"),
    ("Ml",          "ML"),
    ("Nlp",         "NLP"),
    ("Ict",         "ICT"),
    ("Iot",         "IoT"),
    ("Stem",        "STEM"),
    ("Sbir",        "SBIR"),
    ("Sttr",        "STTR"),
    ("Sme",         "SME"),
    ("Ngo",         "NGO"),
    ("Ingo",        "INGO"),
    ("Cso",         "CSO"),
    ("Phd",         "PhD"),
    ("Msc",         "MSc"),
    ("Bsc",         "BSc"),
    ("Mba",         "MBA"),
    ("Mphil",       "MPhil"),
    # Country / region abbreviations used as standalone words in titles
    ("Eu ",         "EU "),
    ("Uk ",         "UK "),
    ("Usa ",        "USA "),
    (" Eu",         " EU"),
    (" Uk",         " UK"),
    (" Usa",        " USA"),
    # Two-letter country codes preceding a hyphen (e.g. "Us-China" → "US-China")
    ("Us-",         "US-"),
    ("Uk-",         "UK-"),
    ("Eu-",         "EU-"),
]

# Compile as whole-word patterns where safe; use simple replace for multi-word
_ACRONYM_PATTERNS: list[tuple[_re.Pattern, str]] = [
    (_re.compile(r'\b' + _re.escape(wrong) + r'\b'), correct)
    for wrong, correct in _ACRONYM_FIXES
    if ' ' not in wrong
]


def _fix_acronyms(text: str | None) -> str | None:
    """Restore incorrectly title-cased acronyms in a free-text field."""
    if not text:
        return text
    for pattern, correct in _ACRONYM_PATTERNS:
        text = pattern.sub(correct, text)
    return text


# ---------------------------------------------------------------------------
# URL pattern blocklist — categorically non-grant URLs
# ---------------------------------------------------------------------------
# These patterns identify URLs that can never be a specific grant opportunity
# page regardless of uniqueness.  Applied before the live-URL validator.

_BLOCKED_URL_PATTERNS_RAW: list[str] = [
    # EU CORDIS — completed/funded project database, never open calls
    r'cordis\.europa\.eu/project/',
    # EU Funding Portal homepage — generic listing
    r'ec\.europa\.eu/info/funding-tenders/opportunities/portal/screen/home',
    # EU success stories — funded project write-ups, not open calls
    r'projects\.research-and-innovation\.ec\.europa\.eu/en/projects/success-stories/',
    # EC open-calls listing page
    r'funding-programmes-and-open-calls',
    # Language-preference query parameter — always a wrong-locale duplicate
    r'[?&]prefLang=',
    # REA news articles — not grant calls
    r'rea\.ec\.europa\.eu/news/',
    # REA reporting pages — grant reporting, not open calls
    r'rea\.ec\.europa\.eu.*grants-reporting',
    # Generic: paginated listing pages (page=2+, pg=2+) are always listings,
    # never a specific grant page.
    r'[?&]page=[2-9]',
    r'[?&]page=1\d',
    r'[?&]pg=[2-9]',
    r'[?&]pg=1\d',
    # Faceted/combined query params that produce listing URLs (e.g. OII ?projects&page=)
    r'[?&]projects&',
    r'[?&]projects$',
]

_BLOCKED_COMPILED: list[_re.Pattern] = [
    _re.compile(p) for p in _BLOCKED_URL_PATTERNS_RAW
]


def _has_bad_url_pattern(url: str | None) -> bool:
    """Return True if url categorically cannot be a specific grant page."""
    if not url:
        return False
    # UKRI: only /opportunity/ sub-paths are actual open-call pages.
    # Every other ukri.org path (/what-we-do/, /publications/, /councils/,
    # /manage-your-award/, gtr.ukri.org/, ?pg= listings, etc.) is guidance,
    # a thematic investment area, or a funded-project record — not an open call.
    if 'ukri.org' in url and '/opportunity/' not in url:
        return True
    return any(p.search(url) for p in _BLOCKED_COMPILED)


def _filter_bad_url_patterns(grants: list[dict]) -> list[dict]:
    """Remove records whose primary URL matches a known non-grant-page pattern."""
    good: list[dict] = []
    dropped = 0
    for g in grants:
        url = g.get("application_portal_url") or g.get("source_url") or ""
        if _has_bad_url_pattern(url):
            dropped += 1
        else:
            good.append(g)
    if dropped:
        print(f"  URL pattern filter: removed {dropped} record(s) with non-grant URLs")
    return good


# ---------------------------------------------------------------------------
# Content verification
# ---------------------------------------------------------------------------
# For each grant we fetch the page and verify:
#   1. HTTP status — drop on explicit 404/410 (page is gone)
#   2. Title match  — at least N significant words from grant_title must appear
#                     in the page text (catches wrong/homepage/tool URLs)
#   3. Deadline year — if a deadline is set, its year must appear on the page
#                      (catches grants whose deadline was hallucinated or
#                       extracted from a different grant on the same listing page)
#
# On timeout, 403, 5xx, or any connection error the grant is KEPT — we cannot
# confirm it is wrong, and bot-blocking is common on funder sites.
# ---------------------------------------------------------------------------

_SKIP_VALIDATION_DOMAINS: frozenset[str] = frozenset(
    {
        # Sites that reliably block automated GET requests but are known-good.
        "researchprofessional.com",
        "thelancet.com",
    }
)

# api_* connectors that CONSTRUCT the opportunity URL from a title-derived slug
# (rather than using an authoritative API/feed-provided link). A guessed slug
# can 404 silently, so these are content-verified like crawled records instead
# of being trusted. Add a domain here whenever a connector builds its URL from
# the title rather than reading it from the source.
_VALIDATE_API_DOMAINS: frozenset[str] = frozenset(
    {
        "api_nserc_canada",   # canada_nserc.py — falls back to _title_to_slug(title)
        "api_ri",             # ireland_ri.py   — builds /funding/{slug}/ from the title
    }
)

_REQUEST_HEADERS: dict[str, str] = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GrantGlobe-Verifier/1.0; "
        "+https://github.com/newlivehung123123/GrantGlobe_prototype)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en",
}

# Words that are too generic to be useful for title matching.
_TITLE_STOPWORDS: frozenset[str] = frozenset(
    {
        "about", "after", "again", "along", "among", "apply", "areas",
        "award", "based", "being", "between", "calls", "comes", "could",
        "doing", "during", "early", "every", "first", "focus", "funds",
        "given", "grant", "grants", "great", "group", "having", "helps",
        "human", "level", "local", "makes", "might", "national", "other",
        "parts", "place", "please", "point", "program", "project", "provide",
        "public", "reach", "research", "right", "since", "small", "start",
        "still", "support", "their", "there", "these", "those", "three",
        "through", "under", "until", "using", "value", "water", "which",
        "while", "within", "world", "would", "years", "young",
    }
)

_DEAD_CODES: frozenset[int] = frozenset({404, 410})

# Minimum significant-word matches required to accept a page as correct.
# Applied only when the title has ≥ 3 significant words.
_TITLE_MIN_MATCHES = 2
_TITLE_MIN_SIG_WORDS = 3  # skip title check for very short titles

# Maximum bytes to read from a page (enough to cover the grant details section).
_MAX_PAGE_BYTES = 80_000


def _significant_title_words(title: str) -> list[str]:
    """Return meaningful words (≥5 chars, not stopwords) from *title*."""
    words = _re.findall(r'[a-zA-Z]{5,}', title.lower())
    return [w for w in words if w not in _TITLE_STOPWORDS]


def _verify_grant(grant: dict, timeout: int = 12) -> tuple[dict, bool, str]:
    """Fetch the grant URL and verify title + deadline against page content.

    Returns (grant, keep, reason_string).

    Drops only when we have a confirmed page fetch AND the content does not
    match the grant record.  All uncertain outcomes (timeout, bot-block,
    connection error) return keep=True.
    """
    from urllib.parse import urlparse as _up

    url = grant.get("application_portal_url") or grant.get("source_url")
    if not url:
        return grant, True, "no_url"

    # API-sourced records are normally authoritative — their URLs come directly
    # from the funder's own database/feed — so we skip content verification.
    # EXCEPTION: connectors that construct the URL from a title-slug guess
    # (_VALIDATE_API_DOMAINS) are verified like crawled records, since a guessed
    # slug can 404 silently.
    grant_domain = grant.get("domain") or ""
    if grant_domain.startswith("api_") and grant_domain not in _VALIDATE_API_DOMAINS:
        return grant, True, "api_source_skip"

    domain = _up(url).netloc.lower().lstrip("www.")
    if any(domain.endswith(s) for s in _SKIP_VALIDATION_DOMAINS):
        return grant, True, "skip_domain"

    title: str = grant.get("grant_title") or ""
    deadline: str | None = grant.get("application_deadline")  # ISO "YYYY-MM-DD" or None

    try:
        req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status in _DEAD_CODES:
                return grant, False, f"http_{resp.status}"

            raw = resp.read(_MAX_PAGE_BYTES)
            charset = resp.headers.get_content_charset("utf-8")
            try:
                page_text = raw.decode(charset, errors="replace")
            except (LookupError, UnicodeDecodeError):
                page_text = raw.decode("utf-8", errors="replace")

            page_lower = page_text.lower()

            # ── Title verification ──────────────────────────────────────
            sig_words = _significant_title_words(title)
            if len(sig_words) >= _TITLE_MIN_SIG_WORDS:
                matches = sum(1 for w in sig_words if w in page_lower)
                if matches < _TITLE_MIN_MATCHES:
                    return grant, False, (
                        f"title_mismatch: {matches}/{len(sig_words)} words found "
                        f"(need {_TITLE_MIN_MATCHES})"
                    )

            # ── Deadline year verification ──────────────────────────────
            # Only apply when we already have a confirmed live page and a
            # specific deadline date (not rolling/TBC grants with NULL deadline).
            if deadline:
                deadline_year = str(deadline)[:4]
                if deadline_year not in page_text:
                    return grant, False, (
                        f"deadline_year_missing: {deadline_year} not on page"
                    )

            return grant, True, "ok"

    except urllib.error.HTTPError as exc:
        if exc.code in _DEAD_CODES:
            return grant, False, f"http_{exc.code}"
        return grant, True, f"http_{exc.code}_keep"
    except Exception as exc:
        # Timeout, connection refused, SSL error, etc. — uncertain, keep.
        return grant, True, f"error_keep: {type(exc).__name__}"


def _filter_live_urls(grants: list[dict], max_workers: int = 15) -> list[dict]:
    """Verify each grant against its URL; drop records that fail content checks.

    Runs concurrently (15 workers) to keep total time manageable.
    Restores original sort order after async completion.
    """
    live: list[dict] = []
    dropped = 0
    drop_reasons: list[str] = []

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_verify_grant, g): g for g in grants}
        for future in as_completed(futures):
            grant, ok, reason = future.result()
            if ok:
                live.append(grant)
            else:
                dropped += 1
                drop_reasons.append(f"  ✗ {grant.get('grant_title', '?')[:60]}  [{reason}]")

    print(f"  Content verification: {len(live)} passed, {dropped} dropped")
    for r in sorted(drop_reasons):
        print(r)

    # Restore original sort order (futures complete out of order)
    id_order = {g["id"]: i for i, g in enumerate(grants)}
    live.sort(key=lambda g: id_order.get(g["id"], 9999))
    return live


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialise_value(key: str, value) -> object:
    """Convert a single psycopg2 field value to a JSON-safe Python object.

    Rules:
    - DATE / DATETIME → ISO 8601 string or null
    - NUMERIC (Decimal) → float or null
    - UUID → string
    - list (TEXT[]) → list (already Python list from psycopg2)
    - array columns that are NULL → []  (never null in output)
    - bool → bool
    - str, int, None → unchanged
    """
    if value is None:
        return [] if key in _ARRAY_COLUMNS else None

    if isinstance(value, (datetime.date, datetime.datetime)):
        return value.isoformat()

    if isinstance(value, decimal.Decimal):
        return float(value)

    if isinstance(value, uuid.UUID):
        return str(value)

    if isinstance(value, list):
        # Ensure every element is a plain string (psycopg2 may return None items)
        return [str(item) for item in value if item is not None]

    return value


def _serialise_row(row: dict) -> dict:
    """Serialise a full database row dict to a JSON-safe dict."""
    result = {key: _serialise_value(key, val) for key, val in row.items()}
    # Defensively decode any leftover HTML entities in free-text fields (some
    # connectors stored raw '&amp;', '&ndash;', '&rsquo;', '&nbsp;' etc.). Applied
    # to every record regardless of source so the public site never shows raw
    # entity codes.
    for _f in ("grant_title", "funder_name", "description"):
        if isinstance(result.get(_f), str):
            result[_f] = html.unescape(result[_f])
    # Restore incorrectly title-cased acronyms in free-text title fields.
    result["grant_title"]  = _fix_acronyms(result.get("grant_title"))
    result["funder_name"]  = _fix_acronyms(result.get("funder_name"))
    return result


# ---------------------------------------------------------------------------
# Main export logic
# ---------------------------------------------------------------------------


def export(include_closed: bool, output_path: Path) -> tuple[int, str]:
    """Connect, query, serialise, and write grants.json.

    Returns a (count, exported_at) tuple: the number of records exported and
    the ISO 8601 timestamp that was written into the JSON metadata.
    Raises SystemExit(1) on connection or query failure.
    """
    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        print(
            "Error: DATABASE_URL is not set.\n"
            "Set it in your environment or in a .env file in this directory, e.g.:\n"
            "  DATABASE_URL=postgresql://user:pass@localhost/grantglobe",
            file=sys.stderr,
        )
        sys.exit(1)

    # ── Connect ────────────────────────────────────────────────────────────
    try:
        conn = psycopg2.connect(database_url)
    except psycopg2.OperationalError as exc:
        print(f"Error: Could not connect to the database.\n{exc}", file=sys.stderr)
        sys.exit(1)

    # ── Query ──────────────────────────────────────────────────────────────
    try:
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_build_query(include_closed))
            rows = cur.fetchall()
    except psycopg2.Error as exc:
        print(f"Error: Database query failed.\n{exc}", file=sys.stderr)
        conn.close()
        sys.exit(1)
    finally:
        conn.close()

    # ── Serialise ──────────────────────────────────────────────────────────
    exported_at = datetime.datetime.now(datetime.timezone.utc).isoformat(
        timespec="seconds"
    )
    grants = [_serialise_row(dict(row)) for row in rows]

    # ── Deduplicate by normalised title + deadline ──────────────────────
    # Keeps the first occurrence (rows are already sorted by status priority
    # then deadline ASC, so the "best" record comes first).
    seen_keys: set[tuple] = set()
    deduped: list[dict] = []
    for g in grants:
        title_norm = (g.get("grant_title") or "").strip().lower()
        deadline = g.get("application_deadline")  # ISO string or None
        key = (title_norm, deadline)
        if key not in seen_keys:
            seen_keys.add(key)
            deduped.append(g)
    if len(deduped) < len(grants):
        print(f"  Deduplication: removed {len(grants) - len(deduped)} duplicate(s)")
    grants = deduped

    # ── URL pattern blocklist — remove categorically non-grant URLs ─────
    grants = _filter_bad_url_patterns(grants)

    # ── URL validation — drop records with broken links ─────────────────
    print(f"  Validating URLs for {len(grants)} records…")
    grants = _filter_live_urls(grants)

    # ── Ranking (Layer 1) — replace the raw SQL ordering with a relevance/
    # quality/urgency score so the default feed leads with the best calls.
    # Annotates each grant with _rank_score (used as the frontend's global prior).
    import ranking
    grants = ranking.rank_grants(grants)
    print(f"  Ranking: scored and ordered {len(grants)} records "
          f"(top score {grants[0]['_rank_score'] if grants else 'n/a'})")

    payload: dict = {
        "metadata": {
            "exported_at": exported_at,
            "total_grants": len(grants),
            "schema_version": "1.0",
            "includes_closed": include_closed,
        },
        "grants": grants,
    }

    # ── Write ──────────────────────────────────────────────────────────────
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    return len(grants), exported_at


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export quality-assured grant records to grants.json.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--include-closed",
        action="store_true",
        default=False,
        help="Include grants whose current_status is 'Closed' (excluded by default).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=_DEFAULT_OUTPUT,
        metavar="PATH",
        help=f"Output path for grants.json (default: {_DEFAULT_OUTPUT}).",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    total, exported_at = export(include_closed=args.include_closed, output_path=args.output)

    print(
        f"\nExport complete.\n"
        f"  Records exported:  {total}\n"
        f"  Includes closed:   {'Yes' if args.include_closed else 'No'}\n"
        f"  Output:            {args.output}\n"
        f"  Exported at:       {exported_at}"
    )


if __name__ == "__main__":
    main()
