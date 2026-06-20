#!/usr/bin/env python3
"""
DST (Department of Science & Technology, India) connector — Stage 2 API source.

Scrapes open calls for proposals from dst.gov.in/call-for-proposals.
No API key required. Server-rendered Drupal 7 HTML table.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/india_dst.py [--dry-run]
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

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DST_BASE = "https://dst.gov.in"
DST_URL = "https://dst.gov.in/call-for-proposals"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Links to individual call detail pages (Drupal node paths under /callforproposals/...)
_LINK_PAT = re.compile(
    r'<a\s[^>]*href="([^"]*callforproposals[^"]*)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_DATE_PAT = re.compile(r'(\d{2}/\d{2}/\d{4})')


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


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(date_str: str) -> str | None:
    try:
        return datetime.datetime.strptime(date_str.strip(), "%d/%m/%Y").strftime("%Y-%m-%d")
    except (ValueError, AttributeError):
        return None


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _fetch_calls() -> list[dict]:
    """
    Extract DST open calls from the listing HTML.

    The page renders one <a href=".../callforproposals/...">Title</a> per call,
    inside a table row that also contains a Start Date and an End Date (both
    DD/MM/YYYY). Rather than depend on exact <td> structure (which varies
    across Drupal themes and may not match what we assume from a converted
    preview), we find every call link and every date in document order, then
    attribute to each link the first two dates that appear after it and
    before the next link — mirroring the proven approach used in
    france_anr.py for ANR's similarly-table-shaped listing.
    """
    html_text = _fetch(DST_URL)
    if not html_text:
        return []

    idx = html_text.find("callforproposals")
    if idx > 0:
        print(f"  DST: first call link at char {idx} ✓")
    else:
        print("  DST WARNING: no callforproposals links found on page")
        print(f"  DST page length: {len(html_text)} chars")
        return []

    links: list[tuple[int, int, str, str]] = []  # (start, end, href, text)
    seen_urls: set[str] = set()
    for m in _LINK_PAT.finditer(html_text):
        href = m.group(1).strip()
        title = _strip_tags(m.group(2)).strip()
        if not title or len(title) < 8:
            continue
        url = href if href.startswith("http") else f"{DST_BASE}{href}"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        links.append((m.start(), m.end(), url, title))

    if not links:
        print("  DST WARNING: callforproposals substring found but no <a> links matched.")
        return []

    date_positions = [(m.start(), m.group(1)) for m in _DATE_PAT.finditer(html_text)]

    calls = []
    for i, (_lstart, lend, url, title) in enumerate(links):
        next_link_start = links[i + 1][0] if i + 1 < len(links) else len(html_text)
        dates_after = [d for pos, d in date_positions if lend <= pos < next_link_start]
        start_raw = dates_after[0] if len(dates_after) >= 1 else None
        end_raw = dates_after[1] if len(dates_after) >= 2 else None
        calls.append({
            "title": title,
            "url": url,
            "start_raw": start_raw,
            "end_raw": end_raw,
            "start_iso": _parse_date(start_raw) if start_raw else None,
            "end_iso": _parse_date(end_raw) if end_raw else None,
        })

    return calls


def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url = opp.get("url", "").strip()
    if not title or not url:
        return None

    return {
        "grant_title":              title,
        "funder_name":              "Department of Science & Technology (DST), India",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              (
            f"Call for proposals issued by India's Department of Science & "
            f"Technology under the Ministry of Science and Technology. "
            f"Full eligibility, scope, and application requirements are "
            f"published on the official call page."
        ),
        "application_deadline":     opp.get("end_iso"),
        "application_deadline_raw": opp.get("end_raw"),
        "grant_opening_date":       opp.get("start_iso"),
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         ["Science & Technology", "Research & Innovation"],
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["South Asia"],
        "geographic_focus_regions": ["South Asia"],
        "applicant_base_countries": ["IN"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_india_dst",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{url}|{title}|{opp.get('end_iso')}".encode()
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
    parser = argparse.ArgumentParser(description="DST India → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching DST India call-for-proposals page …")
    raw_opps = _fetch_calls()
    print(f"  {len(raw_opps)} raw records scraped.")

    today = datetime.date.today()
    mapped = []
    for o in raw_opps:
        g = _map_opportunity(o)
        if not g:
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
        print("\n[DRY RUN] Full records:")
        for g in deduped:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
        return

    conn = _connect()
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    try:
        with conn.cursor() as cur:
            for g in deduped:
                counts[_upsert_grant(cur, g)] += 1
        conn.commit()
    finally:
        conn.close()

    print(f"\nDone: {counts['inserted']} inserted, {counts['updated']} updated, "
          f"{counts['skipped']} skipped.")


if __name__ == "__main__":
    main()
