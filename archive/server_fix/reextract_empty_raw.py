"""
Full re-extraction for approved records with empty raw_extraction.

These records exist in the DB with grant_title / funder_name / source_url
but raw_extraction = {} — so all LLM-derived fields (regions, sectors,
eligibility, status, description, amounts, etc.) are missing.

What this script does:
  1. Fetches every approved record where raw_extraction = '{}'
  2. Locates its cached HTML in raw_cache (same logic as R7 script)
  3. Runs a FULL extraction prompt against Gemini
  4. Normalises the result with normalise_raw_grant() + determine_review_flag()
  5. Updates the record with ALL extracted fields EXCEPT grant_title,
     funder_name, source_url, content_hash, domain, crawl_date
     (identity/quality-assured fields are preserved)
  6. Keeps review_status = 'approved' if requires_review stays False;
     reverts to 'pending' if the new extraction raises a review flag

Key engineering fixes applied (lessons from R7 script):
  - Sleep ONLY before actual API calls (not for HTML-not-found skips)
  - Track api_called counter and sleep when api_called > 0 (before each call)
  - Explicit rate-limit logging (no silent freezes)
  - Fresh DB connection per write (Neon idle-connection timeout ~5 min)
  - max_output_tokens=2048 (full JSON fits; avoids truncation)
  - thinking_budget=0 (no extended thinking — verified as pure overhead)
  - parse_llm_response_tolerant() (handles trailing text, markdown fences)
  - Takes first grant from response list (multi-grant pages: one record per URL)
  - Direct UPDATE by id (not upsert) — bypasses the
    aggregate_confidence_score > existing guard which returns NULL > NULL = false
    for records that have never been scored

Environment (source from .env before running):
  RAW_CACHE_DIR   path to Stage 2 raw_cache
  GOOGLE_API_KEY  Gemini API key (also checked as GEMINI_API_KEY)
  DRY_RUN=1       locate HTML, log what would be done, no API calls or writes
  LIMIT=N         process only first N records

Run from /opt/grantglobe/Stage_3_LLM_extraction with .env sourced:
  set -a && source .env && set +a
  .venv/bin/python /tmp/server_fix/reextract_empty_raw.py
"""

import gzip
import hashlib
import json
import os
import posixpath
import re
import time
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import structlog
from bs4 import BeautifulSoup
from psycopg2.extras import Json

from stage3.db import get_connection
from stage3.normaliser import normalise_raw_grant, determine_review_flag
from stage3.extractor import (
    SYSTEM_PROMPT,
    OUTPUT_FORMAT_INSTRUCTIONS,
    CONTROLLED_VOCAB_HINT,
    parse_llm_response_tolerant,
)

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RAW_CACHE_DIR = Path(
    os.environ.get("RAW_CACHE_DIR", "/opt/grantglobe/Stage_2_crawler/raw_cache")
)
GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY") or os.environ.get("GEMINI_API_KEY")
DRY_RUN = os.environ.get("DRY_RUN") == "1"
LIMIT = int(os.environ.get("LIMIT", "0")) or None
MODEL_NAME = "gemini-3.5-flash"

_HASH_LENGTH = 16
_TRACKING_PARAMS = frozenset([
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "fbclid", "gclid", "msclkid", "twclid", "igshid",
])
_EXTENSION_RE = re.compile(r"\.[a-zA-Z0-9]{1,10}$")


# ---------------------------------------------------------------------------
# URL → url_hash  (mirrors Stage 2 url_canonicaliser exactly)
# ---------------------------------------------------------------------------

def _canonicalise(url: str) -> str:
    if not url or not url.strip():
        return url
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    if scheme == "http":
        scheme = "https"
    hostname = parsed.hostname or ""
    if hostname.startswith("www."):
        hostname = hostname[4:]
    netloc = f"{hostname}:{parsed.port}" if parsed.port else hostname
    path = parsed.path or "/"
    path = posixpath.normpath(path)
    if path == ".":
        path = "/"
    if path.startswith("//"):
        path = "/" + path.lstrip("/")
    path = path.lower()
    if path != "/" and not _EXTENSION_RE.search(path.rsplit("/", 1)[-1]):
        path = path + "/"
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    kept = [(k, v) for k, v in pairs if k.lower() not in _TRACKING_PARAMS]
    query = urlencode(kept)
    return urlunparse((scheme, netloc, path, parsed.params, query, ""))


def _url_to_hash(url: str) -> str:
    return hashlib.sha256(_canonicalise(url).encode()).hexdigest()[:_HASH_LENGTH]


# ---------------------------------------------------------------------------
# Find cached HTML
# ---------------------------------------------------------------------------

def _find_html_file(source_url: str, domain: str, crawl_date) -> Path | None:
    """Return path to the .html cache file, or None if not found."""
    url_hash = _url_to_hash(source_url)
    date_str = str(crawl_date)
    # Primary: exact crawl_date
    candidate = RAW_CACHE_DIR / domain / date_str / "pages" / f"{url_hash}.html"
    if candidate.exists():
        return candidate
    # Fallback: scan other date folders (page may have been crawled on a
    # different cycle date than what is recorded in the grants table).
    domain_dir = RAW_CACHE_DIR / domain
    if domain_dir.is_dir():
        for date_dir in sorted(domain_dir.iterdir(), reverse=True):
            p = date_dir / "pages" / f"{url_hash}.html"
            if p.exists():
                log.debug(
                    "html_found_in_alternate_date",
                    url=source_url,
                    expected=date_str,
                    found=date_dir.name,
                )
                return p
    return None


def _read_html_text(html_path: Path) -> str | None:
    """Decompress + strip HTML to plain text. Returns None on any error."""
    try:
        blob = html_path.read_bytes()
    except OSError:
        return None
    if blob[:2] == b"\x1f\x8b":
        try:
            blob = gzip.decompress(blob)
        except Exception:
            return None
    try:
        html = blob.decode("utf-8", errors="replace")
    except Exception:
        return None
    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception:
        soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    if len(text) < 200:
        return None
    # Truncate to ~6000 tokens ≈ 24000 chars
    return text[:24000]


# ---------------------------------------------------------------------------
# Gemini API call — full extraction
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str) -> str | None:
    """Submit full extraction prompt to Gemini. Returns raw text or None.

    Implements explicit rate-limit logging so waits are visible rather than
    appearing as silent freezes.
    """
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY / GEMINI_API_KEY not set")

    from google import genai as genai_sdk
    from google.genai import types as genai_types

    client = genai_sdk.Client(api_key=GOOGLE_API_KEY)
    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.0,
        max_output_tokens=2048,   # full JSON for one grant ≈ 600-800 tokens; 2048 safe margin
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
    )

    backoffs = [10, 30, 60]
    for attempt in range(len(backoffs) + 1):
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=config,
            )
            return resp.text or ""
        except Exception as exc:
            msg = str(exc).lower()
            is_rate = (
                "429" in msg
                or "quota" in msg
                or "rate" in msg
                or "resource_exhausted" in msg
            )
            if attempt >= len(backoffs):
                log.error("gemini_call_failed_all_retries", error=str(exc))
                return None
            sleep_s = backoffs[attempt]
            if is_rate:
                log.warning(
                    "gemini_rate_limit_waiting",
                    wait_s=sleep_s,
                    attempt=attempt + 1,
                )
            else:
                log.warning(
                    "gemini_transient_error_waiting",
                    wait_s=sleep_s,
                    error=str(exc)[:120],
                    attempt=attempt + 1,
                )
            time.sleep(sleep_s)
    return None


# ---------------------------------------------------------------------------
# DB update
# ---------------------------------------------------------------------------

_UPDATE_SQL = """
UPDATE grants SET
    description                 = %(description)s,
    application_deadline        = %(application_deadline)s,
    application_deadline_raw    = %(application_deadline_raw)s,
    application_deadline_type   = %(application_deadline_type)s,
    deadline_notes              = %(deadline_notes)s,
    eoi_deadline                = %(eoi_deadline)s,
    eoi_deadline_raw            = %(eoi_deadline_raw)s,
    eoi_deadline_type           = %(eoi_deadline_type)s,
    grant_opening_date          = %(grant_opening_date)s,
    grant_opening_date_raw      = %(grant_opening_date_raw)s,
    funding_amount_min          = %(funding_amount_min)s,
    funding_amount_max          = %(funding_amount_max)s,
    currency                    = %(currency)s,
    funding_amount_type         = %(funding_amount_type)s,
    current_status              = %(current_status)s,
    status_source               = %(status_source)s,
    source_language             = %(source_language)s,
    ai_focused                  = %(ai_focused)s,
    individuals_not_eligible    = %(individuals_not_eligible)s,
    organisation_types          = %(organisation_types)s,
    individual_eligibility      = %(individual_eligibility)s,
    applicant_base_regions      = %(applicant_base_regions)s,
    applicant_base_countries    = %(applicant_base_countries)s,
    geographic_focus_regions    = %(geographic_focus_regions)s,
    geographic_focus_countries  = %(geographic_focus_countries)s,
    thematic_sectors            = %(thematic_sectors)s,
    grant_types                 = %(grant_types)s,
    confidence_scores           = %(confidence_scores)s,
    aggregate_confidence_score  = %(aggregate_confidence_score)s,
    raw_extraction              = %(raw_extraction)s,
    requires_review             = %(requires_review)s,
    review_status               = CASE
        WHEN %(requires_review)s = FALSE THEN 'approved'
        ELSE 'pending'
    END,
    updated_at = NOW()
WHERE id = %(id)s
"""

_NORMALISED_SCALAR_FIELDS = [
    "description",
    "application_deadline", "application_deadline_raw", "application_deadline_type",
    "deadline_notes",
    "eoi_deadline", "eoi_deadline_raw", "eoi_deadline_type",
    "grant_opening_date", "grant_opening_date_raw",
    "funding_amount_min", "funding_amount_max", "currency", "funding_amount_type",
    "current_status", "status_source",
    "source_language", "ai_focused",
    "individuals_not_eligible",
    "organisation_types", "individual_eligibility",
    "applicant_base_regions", "applicant_base_countries",
    "geographic_focus_regions", "geographic_focus_countries",
    "thematic_sectors", "grant_types",
    "aggregate_confidence_score",
    "requires_review",
]


def _update_grant(grant_id, normalised: dict, raw_grant: dict) -> bool:
    """Write updated extraction to DB. Opens a fresh connection per call
    to survive Neon's ~5-minute idle-connection timeout.

    Returns True if the record stays approved (requires_review = False).
    """
    params = {field: normalised.get(field) for field in _NORMALISED_SCALAR_FIELDS}
    params["confidence_scores"] = Json(normalised.get("confidence_scores") or {})
    params["raw_extraction"] = Json(raw_grant)
    params["id"] = grant_id

    conn = get_connection()
    try:
        cur = conn.cursor()
        cur.execute(_UPDATE_SQL, params)
        conn.commit()
        cur.close()
    finally:
        conn.close()

    return not normalised["requires_review"]


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Short-lived connection just for the initial SELECT; closed before API loop.
    conn = get_connection()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT id, source_url, domain, crawl_date
        FROM grants
        WHERE requires_review = FALSE
          AND (raw_extraction IS NULL OR raw_extraction = '{}'::jsonb)
        ORDER BY id
        """
        + (f" LIMIT {LIMIT}" if LIMIT else "")
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    total = len(rows)
    log.info(
        "full_reextraction_start",
        total=total,
        dry_run=DRY_RUN,
        raw_cache=str(RAW_CACHE_DIR),
    )

    found_html = 0
    no_html = 0
    api_called = 0
    no_grants_returned = 0
    parse_failed = 0
    updated = 0
    reverted_to_review = 0

    for i, (gid, source_url, domain, crawl_date) in enumerate(rows, 1):

        # ── 1. Locate cached HTML ────────────────────────────────────────────
        html_path = _find_html_file(source_url, domain, crawl_date)
        if html_path is None:
            no_html += 1
            log.debug("html_not_found", id=str(gid), url=source_url)
            continue

        page_text = _read_html_text(html_path)
        if page_text is None:
            no_html += 1
            log.debug("html_too_short_or_unreadable", id=str(gid))
            continue

        found_html += 1

        if DRY_RUN:
            log.info("dry_run_would_extract", id=str(gid), domain=domain)
            continue

        # ── 2. Rate-limit pacing — sleep BEFORE each API call ───────────────
        # Sleep only when a previous API call was made, avoiding wasted waits
        # for no_html records while guaranteeing 4 s gap between real calls.
        if api_called > 0:
            time.sleep(4.0)

        # ── 3. Call Gemini ───────────────────────────────────────────────────
        prompt = (
            SYSTEM_PROMPT
            + "\n\n"
            + OUTPUT_FORMAT_INSTRUCTIONS
            + "\n\n"
            + CONTROLLED_VOCAB_HINT
            + "\n\nPage content:\n"
            + page_text
        )
        raw_text = _call_gemini(prompt)
        api_called += 1

        if raw_text is None:
            log.warning("gemini_no_response", id=str(gid))
            continue

        # ── 4. Parse ─────────────────────────────────────────────────────────
        try:
            grants = parse_llm_response_tolerant(raw_text)
        except ValueError as exc:
            parse_failed += 1
            log.warning("parse_failed", id=str(gid), error=str(exc))
            continue

        if not grants:
            no_grants_returned += 1
            log.debug("no_grants_in_response", id=str(gid), domain=domain)
            continue

        # Take the first grant from the list. Multi-grant pages are rare and
        # the grant.source_url already identifies the specific record we want.
        raw_grant = grants[0]

        # ── 5. Normalise ──────────────────────────────────────────────────────
        source = {
            "source_url": source_url,
            "domain": domain,
            "crawl_date": str(crawl_date),
        }
        normalised = normalise_raw_grant(raw_grant, source)
        review_flag = determine_review_flag(normalised)
        normalised["requires_review"] = review_flag

        # ── 6. Write ──────────────────────────────────────────────────────────
        stayed_approved = _update_grant(gid, normalised, raw_grant)
        updated += 1

        if stayed_approved:
            log.debug("grant_updated_approved", id=str(gid), domain=domain)
        else:
            reverted_to_review += 1
            log.debug("grant_reverted_to_review", id=str(gid), domain=domain)

        # Progress log every 25 API calls
        if api_called % 25 == 0:
            log.info(
                "progress",
                done=i,
                total=total,
                api_called=api_called,
                updated=updated,
                reverted_to_review=reverted_to_review,
            )

    print(f"\n{'DRY RUN — ' if DRY_RUN else ''}Full re-extraction complete")
    print(f"  records examined:      {total}")
    print(f"  HTML found:            {found_html}")
    print(f"  HTML not found:        {no_html}")
    if not DRY_RUN:
        print(f"  API calls made:        {api_called}")
        print(f"  no grants in response: {no_grants_returned}")
        print(f"  parse failed:          {parse_failed}")
        print(f"  records updated:       {updated}")
        print(f"  reverted to review:    {reverted_to_review}")
        print(f"  stayed approved:       {updated - reverted_to_review}")


if __name__ == "__main__":
    main()
