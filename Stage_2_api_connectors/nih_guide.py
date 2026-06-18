#!/usr/bin/env python3
"""
NIH Guide to Grants connector — Stage 2 API source.

Fetches open NIH funding opportunities from the NIH Guide to Grants and
Contracts search API. No API key required.

API endpoint:
  https://grants.nih.gov/funding/searchGuide/search-results-data.cfm

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/nih_guide.py [--dry-run]
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

SEARCH_URL = "https://grants.nih.gov/funding/searchGuide/search-results-data.cfm"
DETAIL_BASE = "https://grants.nih.gov/grants/guide/rfa-files/"
GUIDE_BASE = "https://grants.nih.gov"

ACTIVITY_CODE_SECTORS: dict[str, list[str]] = {
    "R01": ["Health Sciences", "Research & Innovation"],
    "R21": ["Health Sciences", "Research & Innovation"],
    "R03": ["Health Sciences", "Research & Innovation"],
    "R15": ["Health Sciences", "Research & Innovation"],
    "R34": ["Health Sciences", "Research & Innovation"],
    "K01": ["Health Sciences", "Research & Innovation"],
    "K08": ["Health Sciences", "Research & Innovation"],
    "K23": ["Health Sciences", "Research & Innovation"],
    "K99": ["Health Sciences", "Research & Innovation"],
    "F30": ["Health Sciences", "Education & Training"],
    "F31": ["Health Sciences", "Education & Training"],
    "F32": ["Health Sciences", "Education & Training"],
    "T32": ["Health Sciences", "Education & Training"],
    "P01": ["Health Sciences", "Research & Innovation"],
    "U01": ["Health Sciences", "Research & Innovation"],
    "DP1": ["Health Sciences", "Research & Innovation"],
    "DP2": ["Health Sciences", "Research & Innovation"],
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
    if not date_str:
        return None
    date_str = str(date_str).strip()
    for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _fetch_nih_opportunities() -> list[dict]:
    """Fetch all open NIH funding opportunities."""
    params = {
        "Search_Type": "Activity",
        "Activity_Code": "",
        "Grants_Only": "N",
        "Search_Text": "",
        "curr_page": 1,
        "num_records": 200,
        "sort_field": "releasedate",
        "sort_order": "desc",
        "status": "open",
    }
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/javascript, */*",
        "User-Agent": "Mozilla/5.0 (compatible; GrantGlobe/1.0)",
    })

    all_opps: list[dict] = []
    page = 1

    while True:
        params["curr_page"] = page
        try:
            resp = session.get(SEARCH_URL, params=params, timeout=30)
            resp.raise_for_status()
            data = resp.json()
        except Exception as e:
            print(f"  WARNING: NIH fetch failed at page {page}: {e}")
            break

        records = data.get("data") or data.get("records") or []
        if not records:
            # Try alternate key names
            if isinstance(data, list):
                records = data
            else:
                break

        all_opps.extend(records)
        total = data.get("total") or data.get("totalCount") or len(records)
        print(f"  NIH: fetched {len(all_opps)} / {total} …")

        if len(all_opps) >= int(total) or len(records) < params["num_records"]:
            break

        page += 1
        time.sleep(0.5)

    return all_opps


def _map_opportunity(opp: dict) -> dict | None:
    """Map one NIH guide record to a GrantGlobe grant dict."""
    title = (
        opp.get("title") or opp.get("Title") or
        opp.get("opportunity_title") or ""
    ).strip()
    if not title:
        return None

    notice_id = (
        opp.get("noa_id") or opp.get("id") or
        opp.get("notice_id") or opp.get("NoaId") or ""
    ).strip()

    # Build URL from notice ID (e.g. PA-24-123 → grants.nih.gov/grants/guide/pa-files/PA-24-123.html)
    portal_url = None
    if notice_id:
        nid = notice_id.upper()
        if nid.startswith("RFA"):
            portal_url = f"https://grants.nih.gov/grants/guide/rfa-files/{nid}.html"
        elif nid.startswith("PA") or nid.startswith("PAS") or nid.startswith("PAR"):
            portal_url = f"https://grants.nih.gov/grants/guide/pa-files/{nid}.html"
        elif nid.startswith("NOT"):
            portal_url = f"https://grants.nih.gov/grants/guide/notice-files/{nid}.html"
        else:
            portal_url = f"https://grants.nih.gov/grants/guide/pa-files/{nid}.html"

    deadline_raw = (
        opp.get("expiration_date") or opp.get("ExpirationDate") or
        opp.get("close_date") or opp.get("deadline")
    )
    deadline_iso = _parse_date(deadline_raw)

    open_date_raw = (
        opp.get("release_date") or opp.get("ReleaseDate") or
        opp.get("open_date") or opp.get("post_date")
    )
    open_date = _parse_date(open_date_raw)

    activity_code = (
        opp.get("activity_code") or opp.get("ActivityCode") or
        opp.get("activity") or ""
    ).strip().upper()

    institute = (
        opp.get("agency_abbr") or opp.get("AgencyAbbr") or
        opp.get("agency") or "NIH"
    ).strip()
    funder = f"NIH – {institute}" if institute and institute != "NIH" else "National Institutes of Health"

    thematic_sectors = ACTIVITY_CODE_SECTORS.get(
        activity_code, ["Health Sciences", "Research & Innovation"]
    )

    grant_type = "Fellowship" if activity_code.startswith(("F", "K", "T")) else "Research Grant"

    return {
        "grant_title":              title,
        "funder_name":              funder,
        "source_url":               portal_url,
        "application_portal_url":   portal_url,
        "description":              opp.get("description") or opp.get("synopsis"),
        "application_deadline":     deadline_iso,
        "application_deadline_raw": str(deadline_raw) if deadline_raw else None,
        "grant_opening_date":       open_date,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         thematic_sectors,
        "grant_types":              [grant_type],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_nih_guide",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{notice_id}|{title}|{deadline_iso}".encode()
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
        set_clauses = ", ".join(f"{k} = %({k})s" for k in g if k != "source_url")
        cur.execute(
            f"UPDATE grants SET {set_clauses} WHERE id = %(id)s",
            {**g, "id": existing[0]},
        )
        return "updated"
    cols = list(g.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(f'%({c})s' for c in cols)})",
        g,
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="NIH Guide → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching NIH funding opportunities …")
    opps = _fetch_nih_opportunities()
    print(f"  {len(opps)} raw records retrieved.")

    today = datetime.date.today()
    mapped = []
    for o in opps:
        g = _map_opportunity(o)
        if not g or not g.get("source_url") or not g.get("grant_title"):
            continue
        if g["application_deadline"]:
            try:
                if datetime.date.fromisoformat(g["application_deadline"]) < today:
                    continue
            except ValueError:
                pass
        mapped.append(g)

    seen: set[str] = set()
    deduped = [g for g in mapped if not (g["source_url"] in seen or seen.add(g["source_url"]))]
    print(f"  {len(deduped)} grants to upsert after filtering.")

    if args.dry_run:
        print("\n[DRY RUN] First 3 records:")
        for g in deduped[:3]:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
        return

    conn = _connect()
    try:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        for i in range(0, len(deduped), 200):
            batch = deduped[i: i + 200]
            with conn.cursor() as cur:
                for g in batch:
                    counts[_upsert_grant(cur, g)] += 1
            conn.commit()
            print(f"  Progress: {min(i+200, len(deduped))}/{len(deduped)}")
    finally:
        conn.close()

    print(f"\nDone: {counts['inserted']} inserted, {counts['updated']} updated, "
          f"{counts['skipped']} skipped.")


if __name__ == "__main__":
    main()
