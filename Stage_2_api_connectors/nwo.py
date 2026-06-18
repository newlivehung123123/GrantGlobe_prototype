#!/usr/bin/env python3
"""
NWO (Netherlands Organisation for Scientific Research) connector.

Scrapes the NWO open calls listing at nwo.nl/en/calls-for-proposals.
No API key required. Server-rendered HTML.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/nwo.py [--dry-run]
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

NWO_BASE      = "https://www.nwo.nl"
NWO_LIST_URL  = "https://www.nwo.nl/en/calls-for-proposals"
MAX_PAGES     = 20

DOMAIN_SECTOR_MAP: dict[str, list[str]] = {
    "social sciences":       ["Social Sciences & Humanities"],
    "humanities":            ["Social Sciences & Humanities"],
    "natural sciences":      ["Science & Technology"],
    "life sciences":         ["Health Sciences", "Agriculture & Food"],
    "engineering":           ["Science & Technology", "Technology & Innovation"],
    "health":                ["Health Sciences"],
    "climate":               ["Climate & Environment"],
    "environment":           ["Climate & Environment"],
    "education":             ["Education & Training"],
    "innovation":            ["Technology & Innovation"],
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


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    date_str = re.sub(r"\s+", " ", str(date_str)).strip()
    # Remove time portion e.g. "15 March 2026, 14:00"
    date_str = re.sub(r",?\s*\d+:\d+.*", "", date_str).strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _infer_sectors(text: str) -> list[str]:
    text_lower = text.lower()
    sectors: list[str] = []
    for keyword, sector_list in DOMAIN_SECTOR_MAP.items():
        if keyword in text_lower:
            sectors.extend(s for s in sector_list if s not in sectors)
    return sectors or ["Research & Innovation"]


def _fetch_page(session: requests.Session, url: str) -> str | None:
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _parse_calls_from_html(html_text: str) -> list[dict]:
    """
    Extract open calls from NWO listing HTML.

    NWO uses article/card elements for each call. We look for:
      <article ...> or <div class="...call..."> containing a link and metadata.

    The actual CSS classes may vary — we look for any anchor whose href
    contains '/calls/' or '/en/calls/' and extract surrounding context.
    """
    opps: list[dict] = []

    # Find all call detail links  e.g. /en/calls-for-proposals/open-competition-m-2026
    link_pat = re.compile(
        r'<a\s[^>]*href="(/en/calls[^"]+|https://www\.nwo\.nl/en/calls[^"]+)"[^>]*>'
        r'(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    seen_urls: set[str] = set()
    for m in link_pat.finditer(html_text):
        href_raw = m.group(1).strip()
        title_raw = _strip_tags(m.group(2)).strip()

        if not title_raw or len(title_raw) < 5:
            continue
        # Skip navigation/footer links
        if any(skip in href_raw for skip in ["/news/", "/about/", "/contact", "/funding-results"]):
            continue

        url = href_raw if href_raw.startswith("http") else f"{NWO_BASE}{href_raw}"
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # Slice ~2000 chars around this match for metadata
        pos = m.start()
        block = html_text[max(0, pos - 200): pos + 2000]

        # Deadline: look for date patterns near the block
        deadline_raw = None
        deadline_iso = None
        date_pat = re.compile(
            r"(?:deadline|closing|closes?|submission|submit by)[^<]*?"
            r"(\d{1,2}\s+\w+\s+\d{4}|\d{4}-\d{2}-\d{2})",
            re.IGNORECASE,
        )
        dm = date_pat.search(block)
        if dm:
            deadline_raw = dm.group(1)
            deadline_iso = _parse_date(deadline_raw)

        # Description: first <p> text near the block
        desc_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL | re.IGNORECASE)
        description = _strip_tags(desc_m.group(1)).strip()[:400] if desc_m else None

        thematic_sectors = _infer_sectors((title_raw or "") + " " + (description or ""))

        slug = re.search(r"/calls[^/]*/([^/?#]+)/?$", href_raw)
        opp_id = slug.group(1) if slug else href_raw

        opps.append({
            "title":            title_raw,
            "url":              url,
            "deadline_iso":     deadline_iso,
            "deadline_raw":     deadline_raw,
            "description":      description,
            "thematic_sectors": thematic_sectors,
            "opp_id":           opp_id,
        })

    return opps


def _fetch_nwo_opportunities() -> list[dict]:
    session = requests.Session()
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,*/*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
    })

    all_opps: list[dict] = []

    for page_num in range(1, MAX_PAGES + 1):
        # NWO pagination: ?page=0 for page 1, ?page=1 for page 2, etc.
        url = NWO_LIST_URL if page_num == 1 else f"{NWO_LIST_URL}?page={page_num - 1}"
        html_text = _fetch_page(session, url)
        if not html_text:
            print(f"  NWO: page {page_num} returned no content — stopping.")
            break

        if page_num == 1:
            # Diagnostic: show a snippet to confirm parsing targets
            snippet_start = html_text.find("/en/calls")
            if snippet_start > 0:
                print(f"  NWO: first /en/calls href found at char {snippet_start} ✓")
            else:
                print("  NWO WARNING: no /en/calls links found on page 1 — check URL/parsing")
                print(f"  NWO page 1 snippet (chars 5000-6000): {html_text[5000:6000]}")

        page_opps = _parse_calls_from_html(html_text)
        if not page_opps:
            print(f"  NWO: page {page_num} yielded 0 opportunities — stopping.")
            break

        # Deduplicate within this session
        existing_urls = {o["url"] for o in all_opps}
        new_opps = [o for o in page_opps if o["url"] not in existing_urls]
        all_opps.extend(new_opps)
        print(f"  NWO page {page_num}: {len(new_opps)} new opportunities (total: {len(all_opps)})")

        # Stop if no next-page indicator
        if f"page={page_num}" not in html_text and "next" not in html_text.lower():
            break

        time.sleep(0.5)

    return all_opps


def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url   = opp.get("url", "").strip()
    if not title or not url:
        return None

    opp_id = opp.get("opp_id") or url
    deadline_iso = opp.get("deadline_iso")

    return {
        "grant_title":              title,
        "funder_name":              "Netherlands Organisation for Scientific Research",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              opp.get("description"),
        "application_deadline":     deadline_iso,
        "application_deadline_raw": opp.get("deadline_raw"),
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         opp.get("thematic_sectors", ["Research & Innovation"]),
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["NL"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_nwo",
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
    parser = argparse.ArgumentParser(description="NWO → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching NWO open calls …")
    raw_opps = _fetch_nwo_opportunities()
    print(f"  {len(raw_opps)} raw records scraped.")

    today = datetime.date.today()
    mapped = []
    for o in raw_opps:
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
