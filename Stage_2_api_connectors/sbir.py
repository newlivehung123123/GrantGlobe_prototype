#!/usr/bin/env python3
"""
SBIR/STTR connector — Stage 2 API source.

Fetches OPEN SBIR and STTR solicitations from the SBIR.gov public API.
These are calls for proposals (not funded awards), so they represent
genuine application opportunities for small businesses and universities.

SBIR = Small Business Innovation Research
STTR = Small Business Technology Transfer

API docs: https://api.sbir.gov/public/api
No API key required.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/sbir.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SBIR_API_URL = "https://api.sbir.gov/public/api/solicitations"

AGENCY_SECTORS: dict[str, list[str]] = {
    "DOD":  ["Defence & Security", "Technology & Innovation"],
    "HHS":  ["Health Sciences", "Research & Innovation"],
    "NIH":  ["Health Sciences", "Research & Innovation"],
    "NASA": ["Science & Technology", "Technology & Innovation"],
    "NSF":  ["Science & Technology", "Research & Innovation"],
    "DOE":  ["Climate & Environment", "Science & Technology"],
    "USDA": ["Agriculture & Food", "Climate & Environment"],
    "DHS":  ["Defence & Security", "Technology & Innovation"],
    "EPA":  ["Climate & Environment"],
    "DOC":  ["Economic Development", "Technology & Innovation"],
    "DOT":  ["Infrastructure & Urban Development"],
    "ED":   ["Education & Training"],
    "NIJ":  ["Social Sciences & Humanities"],
}

AGENCY_FULL_NAMES: dict[str, str] = {
    "DOD":   "U.S. Department of Defense",
    "HHS":   "U.S. Department of Health and Human Services",
    "NASA":  "National Aeronautics and Space Administration",
    "NSF":   "National Science Foundation",
    "DOE":   "U.S. Department of Energy",
    "USDA":  "U.S. Department of Agriculture",
    "DHS":   "U.S. Department of Homeland Security",
    "EPA":   "U.S. Environmental Protection Agency",
    "DOC":   "U.S. Department of Commerce",
    "DOT":   "U.S. Department of Transportation",
    "ED":    "U.S. Department of Education",
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
    if "T" in date_str:
        date_str = date_str.split("T")[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _fetch_sbir_solicitations() -> list[dict]:
    """
    Fetch open SBIR/STTR solicitations from api.sbir.gov.

    The API returns a list of open solicitations with fields such as:
      solicitation_title, agency, program, solicitation_number,
      open_date, close_date, description, url, solicitation_year
    """
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })

    all_solicitations: list[dict] = []
    start = 0
    rows = 100
    max_records = 2000

    while start < max_records:
        try:
            resp = session.get(
                SBIR_API_URL,
                params={
                    "status": "open",
                    "rows": rows,
                    "start": start,
                },
                timeout=30,
            )
            resp.raise_for_status()

            # Diagnostic on first page so field names are visible in --dry-run
            if start == 0:
                raw = resp.json()
                print(f"  SBIR API response type: {type(raw).__name__}")
                if isinstance(raw, dict):
                    print(f"  SBIR API top-level keys: {list(raw.keys())[:10]}")
                elif isinstance(raw, list) and raw:
                    print(f"  SBIR API first record keys: {list(raw[0].keys())[:15]}")

                # Extract the list from whatever wrapper structure is used
                if isinstance(raw, list):
                    batch = raw
                    total = len(raw)
                elif isinstance(raw, dict):
                    batch = (
                        raw.get("solicitations")
                        or raw.get("data")
                        or raw.get("results")
                        or raw.get("items")
                        or []
                    )
                    total = int(
                        raw.get("count")
                        or raw.get("total")
                        or raw.get("totalCount")
                        or 0
                    )
                else:
                    print("  SBIR: unexpected response format — stopping.")
                    break
            else:
                raw = resp.json()
                if isinstance(raw, list):
                    batch = raw
                    total = 0
                elif isinstance(raw, dict):
                    batch = (
                        raw.get("solicitations")
                        or raw.get("data")
                        or raw.get("results")
                        or raw.get("items")
                        or []
                    )
                    total = int(
                        raw.get("count")
                        or raw.get("total")
                        or raw.get("totalCount")
                        or 0
                    )
                else:
                    break

            if not batch:
                break

            all_solicitations.extend(batch)
            print(f"  SBIR: fetched {len(all_solicitations)} solicitations …")

            if len(batch) < rows:
                break
            start += rows
            time.sleep(0.3)

        except Exception as e:
            print(f"  SBIR API failed at offset {start}: {e}")
            break

    print(f"  SBIR: {len(all_solicitations)} solicitations retrieved.")
    return all_solicitations


def _map_solicitation(s: dict) -> dict | None:
    # Title — try multiple field names in order of likelihood
    title = (
        s.get("solicitation_title")
        or s.get("title")
        or s.get("name")
        or s.get("SolicitationTitle")
        or ""
    ).strip()
    if not title:
        return None

    # Solicitation identifier
    sol_num = str(
        s.get("solicitation_number")
        or s.get("solicitation_id")
        or s.get("id")
        or s.get("SolicitationNumber")
        or ""
    ).strip()

    # URL — construct from ID if not present
    url = (
        s.get("url")
        or s.get("solicitation_url")
        or s.get("link")
        or s.get("SolicitationURL")
        or ""
    ).strip()
    if not url and sol_num:
        url = f"https://www.sbir.gov/solicitations/{sol_num}"
    if not url:
        return None

    # Agency
    agency_raw = (
        s.get("agency")
        or s.get("agency_name")
        or s.get("Agency")
        or ""
    ).strip().upper()
    # Normalise e.g. "Department of Defense" → "DOD"
    agency_key = agency_raw[:5].rstrip()
    funder = AGENCY_FULL_NAMES.get(agency_key, f"U.S. {agency_raw}" if agency_raw else "U.S. Government")

    program = (s.get("program") or s.get("Program") or "SBIR").strip().upper()

    thematic_sectors = list(
        AGENCY_SECTORS.get(agency_key, ["Research & Innovation", "Technology & Innovation"])
    )

    open_date = _parse_date(
        s.get("open_date") or s.get("openDate") or s.get("open") or s.get("OpenDate")
    )
    close_date = _parse_date(
        s.get("close_date") or s.get("closeDate") or s.get("close")
        or s.get("deadline") or s.get("CloseDate")
    )

    description = (
        s.get("description") or s.get("synopsis") or s.get("abstract") or ""
    ).strip()
    if description:
        # Strip HTML tags if present
        description = re.sub(r"<[^>]+>", " ", description)
        description = re.sub(r"\s+", " ", description).strip()[:500]

    sol_id = sol_num or url

    return {
        "grant_title":              title,
        "funder_name":              funder,
        "source_url":               url,
        "application_portal_url":   None,   # source_url is unique per solicitation
        "description":              description or None,
        "application_deadline":     close_date,
        "application_deadline_raw": str(s.get("close_date") or s.get("closeDate") or ""),
        "grant_opening_date":       open_date,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         thematic_sectors,
        "grant_types":              ["Research Grant", "Innovation Grant"],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       ["SME", "University"],
        "individual_eligibility":   [],
        "domain":                   "api_sbir",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{sol_id}|{title}|{close_date}".encode()
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
    parser = argparse.ArgumentParser(description="SBIR/STTR → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching SBIR/STTR open solicitations …")
    raw = _fetch_sbir_solicitations()
    print(f"  {len(raw)} raw records retrieved.")

    today = datetime.date.today()
    mapped = []
    for s in raw:
        g = _map_solicitation(s)
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
