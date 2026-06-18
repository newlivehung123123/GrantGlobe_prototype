#!/usr/bin/env python3
"""
EU Funding Portal connector — Stage 2 API source.

Downloads the public grantsTenders.json file from the EU Funding & Tenders
Portal (no API key required) and upserts clean grant records directly into
the GrantGlobe Postgres database.

Public endpoint:
  https://ec.europa.eu/info/funding-tenders/opportunities/data/referenceData/grantsTenders.json

Also purges contaminated records: rows previously ingested by the LLM crawler
from EC.europa.eu/UKRI listing pages (wrong URL → wrong title/deadline/all fields).

Usage (on the VPS):
    cd /opt/grantglobe
    python3 Stage_2_api_connectors/eu_funding_portal.py [--dry-run] [--purge-only]

Environment variables (same .env as Stage 3):
    DATABASE_URL  — Neon serverless Postgres connection string
"""

from __future__ import annotations

import argparse
import datetime
import json
import hashlib
import os
import sys
import time
from typing import Any

import psycopg2
import psycopg2.extras
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

GRANTS_TENDERS_URL = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/"
    "data/referenceData/grantsTenders.json"
)

PORTAL_BASE = (
    "https://ec.europa.eu/info/funding-tenders/opportunities/"
    "portal/screen/opportunities/topic-details/"
)

# Only ingest these status codes (open or forthcoming)
KEEP_STATUSES = {"OPEN", "FORTHCOMING"}

# Horizon Europe Pillar 2 cluster → thematic sector mapping
CLUSTER_SECTOR_MAP: dict[str, list[str]] = {
    "HORIZON-HLTH":         ["Health Sciences"],
    "HORIZON-CL2":          ["Social Sciences & Humanities"],
    "HORIZON-CL3":          ["Security & Defence"],
    "HORIZON-CL4":          ["Information & Communication Technologies", "Space"],
    "HORIZON-CL5":          ["Energy", "Climate & Environment", "Transport"],
    "HORIZON-CL6":          ["Agriculture & Food", "Climate & Environment"],
    "HORIZON-MISS":         ["Research & Innovation"],
    "HORIZON-ERC":          ["Research & Innovation"],
    "HORIZON-MSCA":         ["Education & Training", "Research & Innovation"],
    "HORIZON-EIC":          ["Technology & Innovation"],
    "HORIZON-EIT":          ["Education & Training", "Technology & Innovation"],
    "HORIZON-WIDERA":       ["Research & Innovation"],
    "HORIZON-JU-IHI":       ["Health Sciences"],
    "HORIZON-JU-CBE":       ["Agriculture & Food", "Climate & Environment"],
    "HORIZON-JTI-CLEANH2":  ["Energy"],
    "HORIZON-JU-Clean-Aviation": ["Transport", "Energy"],
    "HORIZON-KDT-JU":       ["Information & Communication Technologies"],
    "HORIZON-EUROHPC-JU":   ["Information & Communication Technologies"],
    "HORIZON-SESAR":        ["Transport"],
    "HORIZON-JU-SNS":       ["Information & Communication Technologies"],
    "HORIZON-EUSPA":        ["Space"],
}

# Action type → grant_types mapping
ACTION_GRANT_TYPE_MAP: dict[str, list[str]] = {
    "RIA":   ["Research Grant"],
    "IA":    ["Research Grant"],
    "CSA":   ["Research Grant"],
    "ERC":   ["Fellowship", "Research Grant"],
    "MSCA":  ["Fellowship", "Research Grant"],
    "EIC":   ["Innovation Grant"],
    "PCP":   ["Research Grant"],
    "ERA":   ["Research Grant"],
}

# Contaminated source URL patterns to purge (LLM-crawled EC/UKRI listing pages)
PURGE_URL_PATTERNS = [
    # EC portal listing/home pages ingested as individual grant pages
    "ec.europa.eu/info/funding-tenders/opportunities/portal/screen/home",
    "ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/calls-for-proposals",
    "ec.europa.eu/info/funding-tenders/opportunities/portal/screen/opportunities/topic-search",
    # CORDIS project pages (completed projects, not open calls)
    "cordis.europa.eu/project/",
    # UKRI non-opportunity pages
    "ukri.org/what-we-offer/",
    "ukri.org/about-us/",
    "ukri.org/news/",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _ms_to_date(ms: int | None) -> str | None:
    """Convert milliseconds-since-epoch to ISO date string."""
    if ms is None:
        return None
    try:
        return datetime.datetime.utcfromtimestamp(ms / 1000).strftime("%Y-%m-%d")
    except (ValueError, OSError):
        return None


def _extract_cluster_code(call_identifier: str) -> str:
    """
    Extract cluster prefix from a call identifier.
    e.g. "HORIZON-CL5-2023-D2-01" → "HORIZON-CL5"
         "HORIZON-ERC-2025-ADG-01" → "HORIZON-ERC"
    """
    import re
    # Match up to the first 4-digit year segment
    m = re.match(r"^(.+?)-\d{4}-", call_identifier)
    if m:
        return m.group(1)
    return call_identifier.split("-")[0]


def _get_action_type(topic: dict) -> str | None:
    """Extract the first action type abbreviation from topicActions."""
    actions = topic.get("topicActions") or []
    if isinstance(actions, list) and actions:
        first = actions[0]
        if isinstance(first, dict):
            return first.get("abbreviation")
    return None


def _get_deadline(topic: dict) -> tuple[str | None, str | None]:
    """Return (ISO date, raw string) for the earliest upcoming deadline."""
    deadlines_ms: list[int] = topic.get("deadlineDatesLong") or []
    if not deadlines_ms:
        return None, None
    today_ms = time.time() * 1000
    # Prefer the earliest future deadline; fall back to the last one
    future = [d for d in deadlines_ms if d > today_ms]
    chosen_ms = min(future) if future else max(deadlines_ms)
    iso = _ms_to_date(chosen_ms)
    return iso, iso  # raw = iso (already clean from authoritative source)


def _get_budget(topic: dict) -> tuple[float | None, float | None]:
    """Try to extract min/max budget contribution in EUR."""
    budget = topic.get("budgetOverviewContribution") or {}
    max_c = budget.get("maxContribution") or {}
    fixed = max_c.get("fixedAmount")
    if fixed and isinstance(fixed, (int, float)) and fixed > 0:
        return None, float(fixed)
    return None, None


def _map_topic(topic: dict) -> dict:
    """Map one EU portal topic record to a GrantGlobe grant dict."""
    topic_id: str = (topic.get("identifier") or "").strip()
    call_id: str = (topic.get("callIdentifier") or "").strip()
    title: str = (topic.get("title") or "").strip()
    call_title: str = (topic.get("callTitle") or "").strip()

    portal_url = PORTAL_BASE + topic_id.lower() if topic_id else None

    deadline_iso, deadline_raw = _get_deadline(topic)

    cluster_code = _extract_cluster_code(call_id) if call_id else ""
    action_type = _get_action_type(topic)

    thematic_sectors = CLUSTER_SECTOR_MAP.get(cluster_code, ["Research & Innovation"])
    grant_types = ACTION_GRANT_TYPE_MAP.get(action_type or "", ["Research Grant"])

    status_raw = (topic.get("status") or {})
    if isinstance(status_raw, dict):
        status_abbrev = (status_raw.get("abbreviation") or "").upper()
    else:
        status_abbrev = str(status_raw).upper()

    current_status = {
        "OPEN": "Open",
        "FORTHCOMING": "Forthcoming",
        "CLOSED": "Closed",
    }.get(status_abbrev, "Open")

    funding_min, funding_max = _get_budget(topic)

    # Description: use call title + topic description if available
    description_parts = []
    if call_title and call_title.lower() != title.lower():
        description_parts.append(f"Call: {call_title}")
    raw_desc = topic.get("description") or topic.get("objective") or ""
    if raw_desc:
        description_parts.append(raw_desc)
    description = "\n\n".join(description_parts) if description_parts else None

    opening_date = _ms_to_date(topic.get("plannedOpeningDateLong"))

    return {
        # Core identity
        "grant_title":              title or call_title,
        "funder_name":              "European Commission",
        "source_url":               portal_url,
        "application_portal_url":   portal_url,
        "description":              description,
        # Dates
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       opening_date,
        # Status / type
        "current_status":           current_status,
        "source_language":          "en",
        # Budget
        "funding_amount_min":       funding_min,
        "funding_amount_max":       funding_max,
        "currency":                 "EUR" if (funding_min or funding_max) else None,
        # Classification
        "thematic_sectors":         thematic_sectors,
        "grant_types":              grant_types,
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": [],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        # Internal
        "domain":                   "api_eu_portal",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        # content_hash: stable fingerprint so NOT NULL constraint is satisfied
        "content_hash":             hashlib.sha256(
            f"{topic_id}|{title}|{deadline_iso}".encode()
        ).hexdigest(),
        # Lookup key (not a DB column; used for upsert matching)
        "_topic_id":                topic_id,
    }


# ---------------------------------------------------------------------------
# Database helpers
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        # Try loading from Stage 3 .env file
        env_path = os.path.join(
            os.path.dirname(__file__), "..", "Stage_3_LLM_extraction", ".env"
        )
        if os.path.isfile(env_path):
            with open(env_path) as f:
                for line in f:
                    line = line.strip()
                    if line.startswith("DATABASE_URL="):
                        url = line[len("DATABASE_URL="):]
                        break
    if not url:
        sys.exit("ERROR: DATABASE_URL not set and not found in .env file.")
    return url


def _connect() -> psycopg2.extensions.connection:
    url = _get_db_url()
    return psycopg2.connect(url, connect_timeout=30)


def _ensure_domain_column(cur: psycopg2.extensions.cursor) -> None:
    """Add 'domain' column to grants table if it doesn't exist yet."""
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name='grants' AND column_name='domain'
    """)
    if not cur.fetchone():
        cur.execute("ALTER TABLE grants ADD COLUMN domain TEXT")
        print("  Added 'domain' column to grants table.")


def _upsert_grant(cur: psycopg2.extensions.cursor, g: dict) -> str:
    """
    Upsert one grant record. Returns 'inserted', 'updated', or 'skipped'.

    Match key: source_url (unique per topic).
    """
    topic_id = g.pop("_topic_id", None)

    # Check if a record with this URL already exists
    cur.execute(
        "SELECT id, review_status FROM grants WHERE source_url = %s",
        (g["source_url"],)
    )
    existing = cur.fetchone()

    if existing:
        existing_id, existing_review = existing
        # Don't overwrite a manually-approved or manually-rejected record
        if existing_review in ("rejected",):
            return "skipped"
        # Update with fresh authoritative data
        set_clauses = ", ".join(
            f"{k} = %({k})s"
            for k in g
            if k not in ("source_url",)
        )
        cur.execute(
            f"UPDATE grants SET {set_clauses} WHERE id = %(id)s",
            {**g, "id": existing_id},
        )
        return "updated"
    else:
        # Insert new record
        cols = list(g.keys())
        placeholders = ", ".join(f"%({c})s" for c in cols)
        cur.execute(
            f"INSERT INTO grants ({', '.join(cols)}) VALUES ({placeholders})",
            g,
        )
        return "inserted"


def _purge_contaminated(cur: psycopg2.extensions.cursor, dry_run: bool) -> int:
    """
    Mark contaminated LLM-crawled EC/UKRI records as rejected.

    A record is contaminated if:
    - Its source_url or application_portal_url matches a known listing-page pattern
    - It was NOT ingested by this API connector (domain != 'api_eu_portal')
    """
    total = 0
    for pattern in PURGE_URL_PATTERNS:
        like = f"%{pattern}%"
        cur.execute(
            """
            SELECT id FROM grants
            WHERE (source_url ILIKE %s OR application_portal_url ILIKE %s)
              AND (domain IS NULL OR domain != 'api_eu_portal')
              AND review_status != 'rejected'
            """,
            (like, like),
        )
        rows = cur.fetchall()
        if rows:
            ids = [r[0] for r in rows]
            print(f"  Pattern '{pattern}': {len(ids)} record(s) to purge.")
            if not dry_run:
                cur.execute(
                    """
                    UPDATE grants
                    SET review_status = 'rejected',
                        requires_review = false
                    WHERE id = ANY(%s::uuid[])
                    """,
                    (ids,),
                )
            total += len(ids)
    return total


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="EU Funding Portal → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true",
                        help="Parse and print stats without writing to DB")
    parser.add_argument("--purge-only", action="store_true",
                        help="Only run the contaminated-record purge, skip ingestion")
    parser.add_argument("--include-closed", action="store_true",
                        help="Also ingest CLOSED calls (for historical data)")
    args = parser.parse_args()

    # ── Step 1: Download grantsTenders.json ──────────────────────────────────
    if not args.purge_only:
        print(f"Downloading {GRANTS_TENDERS_URL} …")
        try:
            resp = requests.get(GRANTS_TENDERS_URL, timeout=120, stream=True)
            resp.raise_for_status()
        except requests.RequestException as e:
            sys.exit(f"ERROR: Download failed: {e}")

        total_bytes = int(resp.headers.get("content-length", 0))
        data = b""
        for chunk in resp.iter_content(chunk_size=65536):
            data += chunk
        print(f"  Downloaded {len(data):,} bytes.")

        try:
            raw: dict = json.loads(data.decode("utf-8"))
        except json.JSONDecodeError as e:
            sys.exit(f"ERROR: JSON parse failed: {e}")

        topics: list[dict] = raw.get("fundingData", {}).get("GrantTenderObj", [])
        print(f"  {len(topics):,} topics in JSON.")

        # ── Step 2: Filter ────────────────────────────────────────────────────
        today = datetime.date.today()
        keep_statuses = KEEP_STATUSES.copy()
        if args.include_closed:
            keep_statuses.add("CLOSED")

        filtered: list[dict] = []
        for t in topics:
            status_raw = (t.get("status") or {})
            if isinstance(status_raw, dict):
                status = (status_raw.get("abbreviation") or "").upper()
            else:
                status = str(status_raw).upper()

            if status not in keep_statuses:
                continue

            # Skip if ALL deadlines are in the past (for OPEN status)
            if status == "OPEN":
                deadlines_ms = t.get("deadlineDatesLong") or []
                if deadlines_ms:
                    today_ms = time.time() * 1000
                    if all(d < today_ms for d in deadlines_ms):
                        continue  # expired

            # Must have a topic identifier to build a valid URL
            if not (t.get("identifier") or "").strip():
                continue

            filtered.append(t)

        print(f"  {len(filtered):,} topics after status/deadline filter.")

        # ── Step 3: Map to grant dicts ────────────────────────────────────────
        mapped = [_map_topic(t) for t in filtered]

        # Deduplicate by source_url (each topic_id is already unique, but just in case)
        seen_urls: set[str] = set()
        deduped: list[dict] = []
        for g in mapped:
            url = g.get("source_url")
            if url and url not in seen_urls:
                seen_urls.add(url)
                deduped.append(g)
        print(f"  {len(deduped):,} unique grant records to upsert.")

        if args.dry_run:
            print("\n[DRY RUN] First 3 records:")
            for g in deduped[:3]:
                print(json.dumps(
                    {k: v for k, v in g.items() if k != "_topic_id"},
                    indent=2, default=str
                ))
            print(f"\n[DRY RUN] Would upsert {len(deduped)} records. No DB writes.")
        else:
            # ── Step 4: Upsert into DB ────────────────────────────────────────
            conn = _connect()
            try:
                with conn.cursor() as cur:
                    _ensure_domain_column(cur)

                counts = {"inserted": 0, "updated": 0, "skipped": 0}
                BATCH = 200
                for i in range(0, len(deduped), BATCH):
                    batch = deduped[i : i + BATCH]
                    with conn.cursor() as cur:
                        for g in batch:
                            result = _upsert_grant(cur, g)
                            counts[result] += 1
                    conn.commit()
                    print(f"  Progress: {min(i + BATCH, len(deduped))}/{len(deduped)} "
                          f"(+{counts['inserted']} new, ~{counts['updated']} updated)")

                print(f"\nUpsert complete: {counts['inserted']} inserted, "
                      f"{counts['updated']} updated, {counts['skipped']} skipped.")
            finally:
                conn.close()

    # ── Step 5: Purge contaminated records ───────────────────────────────────
    print("\nPurging contaminated LLM-crawled EC/UKRI records …")
    if args.dry_run:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                total = _purge_contaminated(cur, dry_run=True)
            conn.rollback()
        finally:
            conn.close()
        print(f"[DRY RUN] Would purge {total} contaminated records.")
    else:
        conn = _connect()
        try:
            with conn.cursor() as cur:
                total = _purge_contaminated(cur, dry_run=False)
            conn.commit()
        finally:
            conn.close()
        print(f"Purged {total} contaminated records (marked as rejected).")

    print("\nDone.")


if __name__ == "__main__":
    main()
