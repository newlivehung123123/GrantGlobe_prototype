"""
Targeted eligibility re-extraction for remaining R7 'both empty' records.

Scope: grants where
  - requires_review = true AND review_status = 'pending'
  - individuals_not_eligible IS NULL
  - individual_eligibility_raw is empty  (already inferred fix handled non-empty)
  - organisation_types_raw   is empty    (already inferred fix handled non-empty)

For each such record we:
  1. Locate the cached HTML in raw_cache (keyed by url_hash derived from source_url).
  2. Submit a focused eligibility-only prompt to Gemini — cheaper and less risky
     than full re-extraction (no risk of overwriting a good deadline/title).
  3. Parse the response: individuals_not_eligible, individual_eligibility_raw,
     organisation_types_raw.
  4. Merge the new eligibility fields into the existing raw_extraction JSONB.
  5. Re-normalise the merged raw_extraction with normalise_raw_grant().
  6. Write the updated record back; re-evaluate requires_review / review_status.

Environment variables (sourced from .env before running):
  RAW_CACHE_DIR   — path to Stage 2 raw_cache (default: /opt/grantglobe/raw_cache)
  GOOGLE_API_KEY  — Gemini API key (also checked as GEMINI_API_KEY)
  DRY_RUN=1       — scan + locate files, log what would be done, no API calls or writes
  LIMIT=N         — process only the first N records (default: all)

Run from /opt/grantglobe/Stage_3_LLM_extraction with .env sourced:
  set -a && source .env && set +a
  .venv/bin/python -c "import runpy; runpy.run_path('/tmp/server_fix/reextract_r7_eligibility.py', run_name='__main__')"
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
from stage3.normaliser import (
    INDIV_ELIGIBILITY_VOCAB,
    ORG_TYPES_VOCAB,
    normalise_raw_grant,
    determine_review_flag,
)
from stage3.extractor import _with_api_retry

log = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

RAW_CACHE_DIR = Path(os.environ.get("RAW_CACHE_DIR", "/opt/grantglobe/raw_cache"))
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
# Find cached HTML for a grant record
# ---------------------------------------------------------------------------

def _find_html_file(source_url: str, domain: str, crawl_date) -> Path | None:
    """Return path to the .html cache file, or None if not found."""
    url_hash = _url_to_hash(source_url)
    # Primary: exact crawl_date
    date_str = str(crawl_date)
    candidate = RAW_CACHE_DIR / domain / date_str / "pages" / f"{url_hash}.html"
    if candidate.exists():
        return candidate
    # Fallback: scan other date folders under this domain (page may have been
    # crawled on a different cycle date than what's recorded in grants).
    domain_dir = RAW_CACHE_DIR / domain
    if domain_dir.is_dir():
        for date_dir in sorted(domain_dir.iterdir(), reverse=True):
            p = date_dir / "pages" / f"{url_hash}.html"
            if p.exists():
                log.debug("html_found_in_alternate_date", url=source_url,
                          expected=date_str, found=date_dir.name)
                return p
    return None


def _read_html_text(html_path: Path) -> str | None:
    """Decompress + strip HTML to plain text. Returns None on any error."""
    try:
        blob = html_path.read_bytes()
    except OSError:
        return None
    # Decompress if gzip (magic: 0x1f 0x8b)
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
    # Remove script/style noise
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    text = soup.get_text(separator=" ", strip=True)
    # Rough token floor (50 tokens ≈ 200 chars)
    if len(text) < 200:
        return None
    # Truncate to ~6000 tokens ≈ 24000 chars
    return text[:24000]


# ---------------------------------------------------------------------------
# Eligibility-focused Gemini prompt
# ---------------------------------------------------------------------------

_ELIGIBILITY_SYSTEM_PROMPT = f"""\
You are a grant eligibility extraction specialist. Read the grant page text
below and extract ONLY eligibility information.

Return a JSON object (not an array) with EXACTLY these keys:

  "individuals_not_eligible": true if ONLY organisations/institutions can apply
    and individuals cannot apply directly; false if individuals CAN apply;
    null if the page does not say.

  "individual_eligibility_raw": JSON array of strings — the eligible individual
    applicant types exactly as written on the page (use [] if none mentioned).
    Prefer exact wording from this list when it matches:
    {", ".join(INDIV_ELIGIBILITY_VOCAB)}

  "organisation_types_raw": JSON array of strings — eligible organisation types
    exactly as written (use [] if none mentioned).
    Prefer exact wording from this list when it matches:
    {", ".join(ORG_TYPES_VOCAB)}

  "confidence_scores": a JSON object with keys "individual_eligibility" and
    "organisation_types", each valued "high", "medium", "low", or "not_found".

  "raw_notes": any brief note about eligibility ambiguity, or null.

Return ONLY the JSON object — no markdown, no commentary.\
"""


def _build_eligibility_prompt(page_text: str) -> str:
    return _ELIGIBILITY_SYSTEM_PROMPT + "\n\nPage content:\n" + page_text


def _parse_eligibility_response(raw_text: str) -> dict | None:
    """Parse the focused eligibility JSON response. Returns None on failure."""
    s = (raw_text or "").strip()
    # Strip markdown fences
    if s.startswith("```"):
        nl = s.find("\n")
        s = s[nl + 1:] if nl != -1 else ""
        if s.rstrip().endswith("```"):
            s = s.rstrip()[:-3]
        s = s.strip()
    # Find first {
    start = s.find("{")
    if start == -1:
        return None
    try:
        data, _ = json.JSONDecoder().raw_decode(s[start:])
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    return data


# ---------------------------------------------------------------------------
# Gemini API call
# ---------------------------------------------------------------------------

def _call_gemini(prompt: str) -> str | None:
    """Submit prompt to Gemini, return raw text response or None on failure.

    Implements its own rate-limit handling with explicit logging so long waits
    are visible instead of appearing as silent freezes.
    """
    if not GOOGLE_API_KEY:
        raise RuntimeError("GOOGLE_API_KEY / GEMINI_API_KEY not set")
    from google import genai as genai_sdk
    from google.genai import types as genai_types

    client = genai_sdk.Client(api_key=GOOGLE_API_KEY)
    config = genai_types.GenerateContentConfig(
        response_mime_type="application/json",
        temperature=0.0,
        max_output_tokens=512,
        thinking_config=genai_types.ThinkingConfig(thinking_budget=0),
    )

    backoffs = [10, 30, 60]
    for attempt, wait in enumerate([(0, None)] + [(b, b) for b in backoffs]):
        try:
            resp = client.models.generate_content(
                model=MODEL_NAME,
                contents=prompt,
                config=config,
            )
            return resp.text or ""
        except Exception as exc:
            msg = str(exc).lower()
            is_rate = "429" in msg or "quota" in msg or "rate" in msg or "resource_exhausted" in msg
            if attempt >= len(backoffs):
                log.error("gemini_call_failed_all_retries", error=str(exc))
                return None
            sleep_s = backoffs[attempt]
            if is_rate:
                log.warning("gemini_rate_limit_waiting", wait_s=sleep_s, attempt=attempt + 1)
            else:
                log.warning("gemini_transient_error_waiting", wait_s=sleep_s,
                            error=str(exc)[:120], attempt=attempt + 1)
            time.sleep(sleep_s)
    return None


# ---------------------------------------------------------------------------
# DB update
# ---------------------------------------------------------------------------

def _update_grant(grant_id, new_raw: dict, source: dict) -> bool:
    """Re-normalise with updated raw_extraction and write back to grants table.

    Opens a fresh DB connection per call so long-running API loops don't trip
    over Neon's idle-connection timeout (~5 minutes).

    Returns True if the record was moved to approved.
    """
    normalised = normalise_raw_grant(new_raw, source)
    review_flag = determine_review_flag(normalised)
    normalised["requires_review"] = review_flag
    normalised["review_status"] = "pending" if review_flag else "approved"

    conn = get_connection()
    try:
        cur = conn.cursor()
        # Targeted update: only eligibility + review columns + raw_extraction.
        # We do NOT overwrite grant_title, funder_name, deadlines etc. to avoid
        # clobbering known-good data with a single-focused re-extraction.
        cur.execute(
            """
            UPDATE grants SET
                individuals_not_eligible = %(individuals_not_eligible)s,
                individual_eligibility   = %(individual_eligibility)s,
                organisation_types       = %(organisation_types)s,
                raw_extraction           = %(raw_extraction)s,
                requires_review          = %(requires_review)s,
                review_status            = %(review_status)s
            WHERE id = %(id)s
            """,
            {
                "individuals_not_eligible": normalised.get("individuals_not_eligible"),
                "individual_eligibility": normalised.get("individual_eligibility"),
                "organisation_types": normalised.get("organisation_types"),
                "raw_extraction": Json(new_raw),
                "requires_review": normalised["requires_review"],
                "review_status": normalised["review_status"],
                "id": grant_id,
            },
        )
        conn.commit()
        cur.close()
    finally:
        conn.close()
    return not review_flag


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    # Use a short-lived connection just for the initial query, then close it.
    # Each DB write uses its own fresh connection (see _update_grant) to avoid
    # Neon's idle-connection timeout killing a long-running API loop.
    conn = get_connection()
    cur = conn.cursor()

    # The DB column individuals_not_eligible is written as False by the
    # normaliser's `or False` fallback even when the LLM returned null — so we
    # must inspect the raw_extraction JSONB to find the truly-unknown cases.
    # R7 fires when raw_extraction->>'individuals_not_eligible' IS NULL and
    # BOTH individual_eligibility_raw and organisation_types_raw are empty.
    cur.execute(
        """
        SELECT id, source_url, domain, crawl_date, raw_extraction
        FROM grants
        WHERE requires_review = true
          AND review_status   = 'pending'
          AND (raw_extraction->>'individuals_not_eligible') IS NULL
          AND (
                raw_extraction->'individual_eligibility_raw' IS NULL
             OR raw_extraction->'individual_eligibility_raw' = '[]'::jsonb
          )
          AND (
                raw_extraction->'organisation_types_raw' IS NULL
             OR raw_extraction->'organisation_types_raw' = '[]'::jsonb
          )
        ORDER BY id
        """
        + (f" LIMIT {LIMIT}" if LIMIT else "")
    )
    rows = cur.fetchall()
    cur.close()
    conn.close()

    total = len(rows)
    log.info("r7_reextraction_start",
             total=total, dry_run=DRY_RUN, raw_cache=str(RAW_CACHE_DIR))

    found_html = 0
    no_html = 0
    api_called = 0
    updated = 0
    approved = 0

    for i, (gid, source_url, domain, crawl_date, raw_extraction) in enumerate(rows, 1):
        if i > 1:
            time.sleep(4.0)  # unconditional 4s gap — must run before every API call
        html_path = _find_html_file(source_url, domain, crawl_date)
        if html_path is None:
            no_html += 1
            log.debug("html_not_found", id=str(gid), url=source_url)
            continue

        page_text = _read_html_text(html_path)
        if page_text is None:
            no_html += 1
            log.debug("html_too_short_or_unreadable", id=str(gid), url=source_url)
            continue

        found_html += 1

        if DRY_RUN:
            log.info("dry_run_would_extract", id=str(gid), domain=domain)
            continue

        prompt = _build_eligibility_prompt(page_text)
        raw_text = _call_gemini(prompt)
        api_called += 1

        if raw_text is None:
            log.warning("gemini_no_response", id=str(gid))
            continue

        elig = _parse_eligibility_response(raw_text)
        if elig is None:
            log.warning("eligibility_parse_failed", id=str(gid), response=raw_text[:200])
            continue

        # Merge eligibility fields into existing raw_extraction
        raw_grant = dict(raw_extraction or {})
        changed = False

        new_ine = elig.get("individuals_not_eligible")
        new_indiv = elig.get("individual_eligibility_raw") or []
        new_org = elig.get("organisation_types_raw") or []
        new_cs_indiv = (elig.get("confidence_scores") or {}).get("individual_eligibility")
        new_cs_org = (elig.get("confidence_scores") or {}).get("organisation_types")

        if new_ine is not None:
            raw_grant["individuals_not_eligible"] = new_ine
            changed = True
        if new_indiv:
            raw_grant["individual_eligibility_raw"] = new_indiv
            changed = True
        if new_org:
            raw_grant["organisation_types_raw"] = new_org
            changed = True
        # Merge confidence scores (don't overwrite unrelated scores)
        cs = dict(raw_grant.get("confidence_scores") or {})
        if new_cs_indiv:
            cs["individual_eligibility"] = new_cs_indiv
        if new_cs_org:
            cs["organisation_types"] = new_cs_org
        raw_grant["confidence_scores"] = cs

        if not changed:
            log.debug("no_new_eligibility_data", id=str(gid))
            continue

        source = {
            "source_url": source_url,
            "domain": domain,
            "crawl_date": str(crawl_date),
        }
        moved_to_approved = _update_grant(gid, raw_grant, source)
        updated += 1
        if moved_to_approved:
            approved += 1
            log.info("grant_approved", id=str(gid), domain=domain)
        else:
            log.debug("grant_updated_still_review", id=str(gid))

        if api_called % 25 == 0:
            log.info("progress", done=i, total=total,
                     api_called=api_called, approved=approved)

    print(f"\n{'DRY RUN — ' if DRY_RUN else ''}R7 eligibility re-extraction complete")
    print(f"  records examined:   {total}")
    print(f"  HTML found:         {found_html}")
    print(f"  HTML not found:     {no_html}")
    if not DRY_RUN:
        print(f"  API calls made:     {api_called}")
        print(f"  records updated:    {updated}")
        print(f"  moved to approved:  {approved}")


if __name__ == "__main__":
    main()
