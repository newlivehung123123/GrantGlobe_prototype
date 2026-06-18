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
    """Fetch NSF active solicitations from the chronological list."""
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json, text/javascript, */*",
        "User-Agent": "Mozilla/5.0 (compatible; GrantGlobe/1.0)",
    })

    # Try the JSON solicitations list
    try:
        resp = session.get(NSF_SOLICITATIONS_URL, timeout=30)
        resp.raise_for_status()
        data = resp.json()
        records = data if isinstance(data, list) else data.get("solicitations") or data.get("data") or []
        if records:
            print(f"  NSF solicitations JSON: {len(records)} records.")
            return records
    except Exception as e:
        print(f"  NSF JSON feed failed: {e}. Trying program list …")

    # Fallback: NSF new funding opportunities API
    try:
        resp = session.get(
            "https://new.nsf.gov/api/publications/",
            params={
                "type": "solicitation",
                "status": "active",
                "page": 1,
                "per_page": 100,
            },
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        records = data.get("results") or data.get("data") or []
        print(f"  NSF publications API: {len(records)} records.")
        return records
    except Exception as e:
        print(f"  NSF publications API failed: {e}")

    # Last fallback: RSS feed of active solicitations
    try:
        import xml.etree.ElementTree as ET
        resp = session.get(
            "https://www.nsf.gov/rss/rss_www_funding_pgm_announcements.xml",
            timeout=30,
        )
        resp.raise_for_status()
        root = ET.fromstring(resp.content)
        ns = {"atom": "http://www.w3.org/2005/Atom"}
        items = root.findall(".//item") or root.findall(".//atom:entry", ns)
        records = []
        for item in items:
            title = (item.findtext("title") or "").strip()
            link = (item.findtext("link") or "").strip()
            pub_date = (item.findtext("pubDate") or "").strip()
            desc = (item.findtext("description") or "").strip()
            if title and link:
                records.append({
                    "title": title,
                    "link": link,
                    "pubDate": pub_date,
                    "description": desc,
                })
        print(f"  NSF RSS feed: {len(records)} records.")
        return records
    except Exception as e:
        print(f"  NSF RSS feed failed: {e}")

    return []


def _map_solicitation(sol: dict) -> dict | None:
    """Map one NSF solicitation record to a GrantGlobe grant dict."""
    title = (
        sol.get("title") or sol.get("Title") or
        sol.get("programTitle") or ""
    ).strip()
    if not title:
        return None

    # URL
    portal_url = (
        sol.get("link") or sol.get("url") or sol.get("href") or
        sol.get("pubs_id") or sol.get("id")
    )
    if portal_url and not portal_url.startswith("http"):
        # Could be a pub number like nsf24123
        if re.match(r"nsf\d+", str(portal_url), re.IGNORECASE):
            portal_url = f"https://www.nsf.gov/pubs/{portal_url}/"
        else:
            portal_url = f"https://www.nsf.gov{portal_url}"

    if not portal_url:
        return None

    # Deadline
    deadline_raw = (
        sol.get("deadline") or sol.get("due_date") or
        sol.get("close_date") or sol.get("expiration_date")
    )
    deadline_iso = _parse_date(deadline_raw)

    open_date_raw = (
        sol.get("pubDate") or sol.get("pub_date") or
        sol.get("open_date") or sol.get("release_date")
    )
    open_date = _parse_date(open_date_raw)

    # Division → sector
    division = (
        sol.get("division") or sol.get("directorate") or
        sol.get("org") or ""
    ).upper()[:3]
    thematic_sectors = DIVISION_SECTOR_MAP.get(division, ["Research & Innovation", "Science & Technology"])

    sol_id = str(sol.get("id") or sol.get("pubs_id") or sol.get("program_id") or "")

    return {
        "grant_title":              title,
        "funder_name":              "National Science Foundation",
        "source_url":               portal_url,
        "application_portal_url":   portal_url,
        "description":              sol.get("description") or sol.get("synopsis"),
        "application_deadline":     deadline_iso,
        "application_deadline_raw": str(deadline_raw) if deadline_raw else None,
        "grant_opening_date":       open_date,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
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
            f"{sol_id}|{title}|{deadline_iso}".encode()
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

    print("Fetching NSF funding opportunities …")
    sols = _fetch_nsf_solicitations()
    print(f"  {len(sols)} raw records retrieved.")

    today = datetime.date.today()
    mapped = []
    for s in sols:
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
