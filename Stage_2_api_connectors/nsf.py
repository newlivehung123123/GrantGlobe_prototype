#!/usr/bin/env python3
"""
NSF funding opportunities connector — Stage 2 API source.

Fetches open NSF program solicitations and funding opportunities.
No API key required.

NSF publishes active solicitations via a public search endpoint.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/nsf.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
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

# NSF active funding opportunities search API
NSF_SEARCH_URL = "https://www.nsf.gov/funding/pgm_list.jsp"
NSF_API_URL = "https://www.nsf.gov/awardsearch/advancedSearchResult"

# NSF publishes a JSON feed of open program solicitations
NSF_SOLICITATIONS_URL = (
    "https://www.nsf.gov/pubs/chronological/solicit_chron_list.json"
)
NSF_PROGRAM_URL = "https://new.nsf.gov/funding/opportunities"
NSF_DETAIL_BASE = "https://www.nsf.gov/pubs/"

DIVISION_SECTOR_MAP: dict[str, list[str]] = {
    "BIO": ["Agriculture & Food", "Climate & Environment"],
    "CISE": ["Information & Communication Technologies"],
    "EDU": ["Education & Training"],
    "ENG": ["Science & Technology"],
    "GEO": ["Climate & Environment"],
    "MPS": ["Science & Technology"],
    "SBE": ["Social Sciences & Humanities"],
    "TIP": ["Technology & Innovation"],
    "OD": ["Research & Innovation"],
    "OISE": ["Research & Innovation"],
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


def _fetch_nsf_solicitations() -> list[dict]:
    """
    Fetch NSF active awards from the public NSF Awards API.

    NSF's new funding opportunities site (new.nsf.gov) is a JS-rendered SPA
    with no accessible JSON API. Open NSF solicitations are also indexed on
    grants.gov (covered by the grants_gov connector). Here we use the NSF
    Awards API to pull currently active awards — these represent programs NSF
    is actively funding, giving users real grant titles and program areas to
    search. We de-duplicate by directorate/division so we show programs, not
    individual awards.

    API docs: https://www.research.gov/common/webapi/awardapisearch-v1.htm
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

    FIELDS = (
        "id,title,agency,awardeeName,startDate,expDate,abstractText,"
        "pdPIName,fundProgramName,dirAbbr,divAbbr,estimatedTotalAmt"
    )

    awards: list[dict] = []
    offset = 1
    rpp = 100
    max_records = 500  # cap; NSF DB has ~10k recent awards

    while offset <= max_records:
        try:
            resp = session.get(
                "https://api.nsf.gov/services/v1/awards.json",
                params={
                    "dateStart": "01/01/2024",  # awards started since Jan 2024
                    "printFields": FIELDS,
                    "offset": offset,
                    "rpp": rpp,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            batch = data.get("response", {}).get("award", [])
            if not batch:
                break
            # Filter to currently active awards only (expDate in future)
            today_str = datetime.date.today().strftime("%m/%d/%Y")
            batch = [a for a in batch if a.get("activeAwd") == "true"]
            awards.extend(batch)
            total = int(data.get("response", {}).get("totalCount", 0) or 0)
            print(f"  NSF Awards API: fetched {len(awards)}/{min(total, max_records) if total else '?'} active …")
            if len(data.get("response", {}).get("award", [])) < rpp:
                break
            offset += rpp
            time.sleep(0.3)
        except Exception as e:
            print(f"  NSF Awards API failed at offset {offset}: {e}")
            break

    print(f"  NSF: {len(awards)} active award records retrieved.")
    return awards


def _map_solicitation(award: dict) -> dict | None:
    """
    Map one NSF Awards API record to a GrantGlobe grant dict.

    IMPORTANT: these are *awards already made* (activeAwardProject=true) — money
    already disbursed to named researchers — NOT open funding calls anyone can
    apply to. They are therefore mapped with current_status="Closed" so the
    default export (which excludes Closed) keeps them off the live site. NSF's
    open solicitations are largely cross-posted to grants.gov, which GrantGlobe
    already ingests.
    TODO: replace this Awards-API source with NSF's open-opportunities feed.
    """
    title = html.unescape((award.get("title") or "").strip())
    if not title:
        return None

    award_id = str(award.get("id") or "")
    if not award_id:
        return None

    # Human-readable NSF award detail page. (The previous research.gov
    # awardapi-service URL was a raw XML/JSON API endpoint, not a viewable page.)
    portal_url = f"https://www.nsf.gov/awardsearch/showAward?AWD_ID={award_id}"

    # NSF open solicitations search (generic link for context)
    nsf_search = "https://new.nsf.gov/funding/opportunities"

    # Directorate → sector
    dir_abbr = (award.get("dirAbbr") or "").upper()[:4].rstrip()
    thematic_sectors = DIVISION_SECTOR_MAP.get(
        dir_abbr, ["Research & Innovation", "Science & Technology"]
    )

    # Funding amount
    amt_raw = award.get("estimatedTotalAmt")
    try:
        funding_max = float(amt_raw) if amt_raw else None
    except (ValueError, TypeError):
        funding_max = None

    # Dates: startDate is when award was made, expDate is when award expires.
    # We use expDate as the "deadline" (end of currently active award).
    open_date = _parse_date(award.get("startDate"))
    exp_date  = _parse_date(award.get("expDate"))

    # Program name for richer description
    prog_name = (award.get("fundProgramName") or "").strip()
    awardee   = (award.get("awardeeName") or "").strip()
    abstract  = html.unescape((award.get("abstractText") or "").strip())
    description = (
        f"[Active NSF Award — {prog_name}] Awardee: {awardee}. {abstract[:500]}"
        if abstract else
        f"Active NSF award in program: {prog_name}. Awardee: {awardee}."
    )

    return {
        "grant_title":              title,
        "funder_name":              "National Science Foundation",
        "source_url":               portal_url,
        "application_portal_url":   None,   # portal_url is unique per award; NULL lets export uniqueness check use source_url
        "description":              description,
        "application_deadline":     exp_date,    # award expiry (active until then)
        "application_deadline_raw": award.get("expDate"),
        "grant_opening_date":       open_date,
        # Already-disbursed award, not an open call — see docstring. Closed keeps
        # it out of the default (Closed-excluding) export and off the live site.
        "current_status":           "Closed",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       funding_max,
        "currency":                 "USD" if funding_max else None,
        "thematic_sectors":         thematic_sectors,
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_nsf",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{award_id}|{title}|{exp_date}".encode()
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
    parser = argparse.ArgumentParser(description="NSF → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching NSF active awards …")
    awards = _fetch_nsf_solicitations()
    print(f"  {len(awards)} raw records retrieved.")

    today = datetime.date.today()
    mapped = []
    for a in awards:
        g = _map_solicitation(a)
        if not g or not g.get("source_url") or not g.get("grant_title"):
            continue
        # Keep awards that are currently active (expDate in the future, or no expDate)
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
