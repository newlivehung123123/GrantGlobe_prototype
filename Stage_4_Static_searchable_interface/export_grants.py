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
# URL validation
# ---------------------------------------------------------------------------

_SKIP_VALIDATION_DOMAINS = {
    # Sites that block automated HEAD requests but are known-good
    "researchprofessional.com",
    "thelancet.com",
}

_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; GrantGlobe-LinkChecker/1.0; "
        "+https://github.com/newlivehung123123/GrantGlobe_prototype)"
    )
}


def _check_url(url: str, timeout: int = 8) -> bool:
    """Return False ONLY on explicit 404/410 (page definitively gone).

    All other outcomes (403 Forbidden, timeout, connection error, 5xx) return
    True — the grant is kept.  This avoids false positives from sites that
    block bot traffic or are temporarily slow.
    """
    if not url:
        return True

    from urllib.parse import urlparse
    domain = urlparse(url).netloc.lower().lstrip("www.")
    if any(domain.endswith(skip) for skip in _SKIP_VALIDATION_DOMAINS):
        return True

    _DEAD_CODES = {404, 410}

    try:
        req = urllib.request.Request(url, method="HEAD", headers=_REQUEST_HEADERS)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status not in _DEAD_CODES
    except urllib.error.HTTPError as e:
        if e.code == 405:
            # Server rejected HEAD — try GET
            try:
                req = urllib.request.Request(url, headers=_REQUEST_HEADERS)
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    return resp.status not in _DEAD_CODES
            except urllib.error.HTTPError as e2:
                return e2.code not in _DEAD_CODES
            except Exception:
                return True  # uncertain — keep
        return e.code not in _DEAD_CODES
    except Exception:
        return True  # timeout / connection error — keep, not confirmed dead


def _filter_live_urls(grants: list[dict], max_workers: int = 20) -> list[dict]:
    """Remove grants whose primary URL returns a 4xx/5xx response.

    Checks application_portal_url first; falls back to source_url.
    Runs concurrently to keep total time under ~60 s for 300+ records.
    """
    def _check(grant: dict) -> tuple[dict, bool]:
        url = grant.get("application_portal_url") or grant.get("source_url")
        return grant, _check_url(url)

    live: list[dict] = []
    dropped = 0
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_check, g): g for g in grants}
        for future in as_completed(futures):
            grant, ok = future.result()
            if ok:
                live.append(grant)
            else:
                dropped += 1

    print(f"  URL validation: {len(live)} live, {dropped} dropped (broken links)")
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

    # ── URL validation — drop records with broken links ─────────────────
    print(f"  Validating URLs for {len(grants)} records…")
    grants = _filter_live_urls(grants)

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
