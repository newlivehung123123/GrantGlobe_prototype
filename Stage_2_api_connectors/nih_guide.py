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
NIH_RSS_BASE = "https://grants.nih.gov/rss/"

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
    """
    Fetch open NIH funding opportunities via the NIH Guide RSS feeds.
    NIH publishes separate RSS feeds for RFAs (Requests for Applications)
    and PAs (Program Announcements) — both are open funding opportunities.
    """
    import xml.etree.ElementTree as ET

    session = requests.Session()
    session.headers.update({
        "Accept": "application/rss+xml, application/xml, text/xml, */*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })

    rss_feeds = [
        ("RFA", "https://grants.nih.gov/rss/rss_active_rfas.cfm"),
        ("PA",  "https://grants.nih.gov/rss/rss_active_pas.cfm"),
    ]

    all_opps: list[dict] = []

    for feed_type, feed_url in rss_feeds:
        try:
            resp = session.get(feed_url, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
            items = root.findall(".//item")
            print(f"  NIH {feed_type} RSS: {len(items)} items.")
            for item in items:
                title = (item.findtext("title") or "").strip()
                link = (item.findtext("link") or "").strip()
                pub_date = (item.findtext("pubDate") or "").strip()
                desc = (item.findtext("description") or "").strip()
                # Extract notice ID from link (e.g. RFA-CA-24-001)
                notice_id = ""
                if link:
                    import re
                    m = re.search(r"((?:RFA|PA[SR]?|NOT|OD)-[\w-]+)", link, re.IGNORECASE)
                    if m:
                        notice_id = m.group(1).upper()
                if title and link:
                    all_opps.append({
                        "title": title,
                        "link": link,
                        "pubDate": pub_date,
                        "description": desc,
                        "notice_id": notice_id,
                        "feed_type": feed_type,
                    })
        except Exception as e:
            print(f"  WARNING: NIH {feed_type} RSS feed failed: {e}")

    print(f"  NIH total: {len(all_opps)} opportunities from RSS feeds.")
    return all_opps


def _map_opportunity(opp: dict) -> dict | None:
    """Map one NIH RSS item to a GrantGlobe grant dict."""
    import re

    title = (opp.get("title") or "").strip()
    if not title:
        return None

    portal_url = (opp.get("link") or "").strip() or None
    notice_id = (opp.get("notice_id") or "").strip()

    # RSS pubDate is the release date; NIH doesn't include deadline in RSS.
    # Deadline is left null — the export filter keeps null-deadline grants.
    open_date = _parse_date(opp.get("pubDate"))

    # Infer activity code from notice_id or title
    activity_code = ""
    if notice_id:
        m = re.match(r"(?:RFA|PA[SR]?)-([A-Z]{2})-", notice_id)
        if m:
            activity_code = ""  # institute code, not activity code
    # Try to extract from title (e.g. "R01 Research Project Grant")
    m2 = re.search(r'\b([RTKUFPDCS]\d{2})\b', title)
    if m2:
        activity_code = m2.group(1).upper()

    funder = "National Institutes of Health"
    thematic_sectors = ACTIVITY_CODE_SECTORS.get(
        activity_code, ["Health Sciences", "Research & Innovation"]
    )
    grant_type = "Fellowship" if activity_code.startswith(("F", "K", "T")) else "Research Grant"

    return {
        "grant_title":              title,
        "funder_name":              funder,
        "source_url":               portal_url,
        "application_portal_url":   portal_url,
        "description":              opp.get("description") or None,
        "application_deadline":     None,   # not in RSS; kept for review
        "application_deadline_raw": None,
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
            f"{notice_id}|{title}|{portal_url}".encode()
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
