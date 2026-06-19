#!/usr/bin/env python3
"""
Grants.gov connector — Stage 2 API source.

Fetches open and forecasted US federal grant opportunities from grants.gov.
No API key required.

API endpoint:
  POST https://apply07.grants.gov/grantsws/rest/opportunities/search/

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/grants_gov.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import time

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SEARCH_URL = "https://apply07.grants.gov/grantsws/rest/opportunities/search/"
DETAIL_BASE = "https://grants.gov/search-results-detail/"

# Opportunity statuses to ingest
KEEP_STATUSES = {"posted", "forecasted"}

# Category → thematic sectors
CATEGORY_SECTOR_MAP: dict[str, list[str]] = {
    "AR": ["Arts & Culture"],
    "AG": ["Agriculture & Food"],
    "BC": ["Economic Development"],
    "CD": ["Community Development"],
    "CP": ["Climate & Environment"],
    "DPR": ["Disaster Relief"],
    "ED": ["Education & Training"],
    "ELT": ["Education & Training"],
    "EN": ["Energy"],
    "ENV": ["Climate & Environment"],
    "FN": ["Financial Services"],
    "HL": ["Health Sciences"],
    "HO": ["Housing"],
    "HU": ["Humanities & Social Sciences"],
    "IIJ": ["Justice & Law"],
    "IS": ["Information & Communication Technologies"],
    "LJL": ["Justice & Law"],
    "MH": ["Health Sciences"],
    "NR": ["Climate & Environment"],
    "OZ": ["Other"],
    "RA": ["Research & Innovation"],
    "RD": ["Research & Innovation"],
    "ST": ["Science & Technology"],
    "T": ["Transport"],
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
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
        sys.exit("ERROR: DATABASE_URL not set.")
    return url


def _connect():
    return psycopg2.connect(_get_db_url(), connect_timeout=30)


def _parse_date(date_str: str | None) -> str | None:
    """Parse MM/DD/YYYY or YYYY-MM-DD to ISO YYYY-MM-DD."""
    if not date_str:
        return None
    date_str = date_str.strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m-%d-%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _fetch_all_opportunities() -> list[dict]:
    """Fetch all posted/forecasted opportunities from grants.gov in pages."""
    all_opps = []
    start = 0
    page_size = 25
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
    })

    while True:
        payload = {
            "oppNum": "",
            "keyword": "",
            "startRecordNum": start,
            "oppStatuses": "posted|forecasted",
            "rows": page_size,
            "sortBy": "openDate|desc",
            "cfda": "",
            "fundingCategoryEligs": "",
            "eligibilities": "",
            "agencyCode": "",
        }
        try:
            resp = session.post(SEARCH_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  WARNING: page fetch failed at start={start}: {e}")
            break

        opps = data.get("oppHits", [])
        if not opps:
            break

        all_opps.extend(opps)
        # totalCount may be 0 or missing — use len(opps) < page_size as stop signal
        total = int(data.get("totalCount") or 0)
        if total > 0:
            print(f"  Fetched {len(all_opps)}/{total} opportunities …")
        else:
            print(f"  Fetched {len(all_opps)} opportunities …")

        start += page_size
        # Stop if: we reached totalCount, or got a partial page (last page)
        if (total > 0 and start >= total) or len(opps) < page_size:
            break
        time.sleep(0.3)  # be polite

    return all_opps


def _map_opportunity(opp: dict) -> dict:
    """Map one grants.gov opportunity to a GrantGlobe grant dict."""
    opp_id = str(opp.get("id") or opp.get("oppNum") or "")
    title = (opp.get("title") or "").strip()
    agency = (opp.get("agencyName") or opp.get("agency") or "US Federal Government").strip()
    status = (opp.get("oppStatus") or "").lower()
    category_code = (opp.get("fundingCategory") or "").upper()

    deadline_raw = opp.get("closeDate") or opp.get("deadlineDate")
    deadline_iso = _parse_date(deadline_raw)

    open_date = _parse_date(opp.get("openDate") or opp.get("postDate"))

    # URL: use the grants.gov detail page
    opp_number = opp.get("number") or opp.get("oppNum") or opp_id
    portal_url = f"{DETAIL_BASE}{opp_number}" if opp_number else None

    # Budget
    award_floor = opp.get("awardFloor")
    award_ceiling = opp.get("awardCeiling")
    try:
        funding_min = float(award_floor) if award_floor else None
        funding_max = float(award_ceiling) if award_ceiling else None
    except (ValueError, TypeError):
        funding_min = funding_max = None

    current_status = {
        "posted": "Open",
        "forecasted": "Forthcoming",
        "closed": "Closed",
        "archived": "Closed",
    }.get(status, "Open")

    thematic_sectors = CATEGORY_SECTOR_MAP.get(category_code, ["Research & Innovation"])

    description = opp.get("synopsis") or opp.get("description") or None

    return {
        "grant_title":              title,
        "funder_name":              agency,
        "source_url":               portal_url,
        "application_portal_url":   portal_url,
        "description":              description,
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       open_date,
        "current_status":           current_status,
        "source_language":          "en",
        "funding_amount_min":       funding_min,
        "funding_amount_max":       funding_max,
        "currency":                 "USD" if (funding_min or funding_max) else None,
        "thematic_sectors":         thematic_sectors,
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_grants_gov",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{opp_id}|{title}|{deadline_iso}".encode()
        ).hexdigest(),
    }


def _upsert_grant(cur, g: dict) -> str:
    cur.execute(
        "SELECT id, review_status FROM grants WHERE source_url = %s",
        (g["source_url"],)
    )
    existing = cur.fetchone()
    if existing:
        if existing[1] == "rejected":
            return "skipped"
        set_clauses = ", ".join(
            f"{k} = %({k})s" for k in g if k != "source_url"
        )
        cur.execute(
            f"UPDATE grants SET {set_clauses} WHERE id = %(id)s",
            {**g, "id": existing[0]},
        )
        return "updated"
    else:
        cols = list(g.keys())
        placeholders = ", ".join(f"%({c})s" for c in cols)
        cur.execute(
            f"INSERT INTO grants ({', '.join(cols)}) VALUES ({placeholders})", g
        )
        return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Grants.gov → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching opportunities from grants.gov …")
    opps = _fetch_all_opportunities()
    print(f"  {len(opps)} opportunities retrieved.")

    today = datetime.date.today()
    mapped = []
    for o in opps:
        g = _map_opportunity(o)
        if not g["source_url"] or not g["grant_title"]:
            continue
        # Drop if deadline is in the past
        if g["application_deadline"]:
            try:
                dl = datetime.date.fromisoformat(g["application_deadline"])
                if dl < today:
                    continue
            except ValueError:
                pass
        mapped.append(g)

    # Deduplicate by source_url
    seen: set[str] = set()
    deduped = []
    for g in mapped:
        url = g["source_url"]
        if url not in seen:
            seen.add(url)
            deduped.append(g)

    print(f"  {len(deduped)} grants to upsert after filtering.")

    if args.dry_run:
        print("\n[DRY RUN] First 3 records:")
        for g in deduped[:3]:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
        return

    conn = _connect()
    counts = {"inserted": 0, "updated": 0, "skipped": 0, "errors": 0}
    try:
        for i, g in enumerate(deduped, 1):
            try:
                with conn.cursor() as cur:
                    result = _upsert_grant(cur, g)
                conn.commit()
                counts[result] += 1
            except Exception as e:
                # Per-record commit (rather than per-200-batch) means a single
                # bad record only rolls back that one statement instead of
                # aborting the whole run and losing every record already
                # processed in the batch. Mirrors the per-record try/except
                # pattern already used in usda_nifa.py and cihr_canada.py.
                conn.rollback()
                if "grants_content_hash_key" in str(e):
                    # Harmless duplicate: two grants.gov opportunities shared
                    # the same id/title/deadline under different source_urls,
                    # so the source_url lookup missed the existing row and we
                    # tried to INSERT a second copy. Not a real failure.
                    counts["skipped"] += 1
                else:
                    print(f"  DB error {g.get('source_url')}: {e}", file=sys.stderr)
                    counts["errors"] += 1
            if i % 200 == 0 or i == len(deduped):
                print(f"  Progress: {i}/{len(deduped)} (+{counts['inserted']} new)")
    finally:
        conn.close()

    print(f"\nDone: {counts['inserted']} inserted, {counts['updated']} updated, "
          f"{counts['skipped']} skipped, {counts['errors']} errors.")


if __name__ == "__main__":
    main()
