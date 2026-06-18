#!/usr/bin/env python3
"""
NSERC (Natural Sciences and Engineering Research Council of Canada) connector.

Scrapes open funding opportunities from nserc-crsng.canada.ca.
No API key required. Server-rendered listing page; individual pages are
JS-rendered so source URLs are constructed from title slugs.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/canada_nserc.py [--dry-run]
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

NSERC_BASE     = "https://nserc-crsng.canada.ca"
NSERC_LIST_URL = "https://nserc-crsng.canada.ca/en/funding/funding-opportunity"
MAX_PAGES      = 10

DOMAIN_SECTOR_MAP: dict[str, list[str]] = {
    "health":         ["Health Sciences"],
    "medical":        ["Health Sciences"],
    "environment":    ["Climate & Environment"],
    "climate":        ["Climate & Environment"],
    "ocean":          ["Climate & Environment"],
    "forest":         ["Climate & Environment", "Agriculture & Food"],
    "agriculture":    ["Agriculture & Food"],
    "food":           ["Agriculture & Food"],
    "engineering":    ["Science & Technology", "Technology & Innovation"],
    "technology":     ["Science & Technology", "Technology & Innovation"],
    "quantum":        ["Science & Technology", "Technology & Innovation"],
    "innovation":     ["Technology & Innovation"],
    "social":         ["Social Sciences & Humanities"],
    "indigenous":     ["Social Services & Welfare"],
    "education":      ["Education & Training"],
    "training":       ["Education & Training"],
    "research":       ["Research & Innovation"],
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
    date_str = re.sub(r",?\s*\d+:\d+.*", "", date_str).strip()
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y",
                "%d/%m/%Y", "%m/%d/%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _title_to_slug(title: str) -> str:
    """Convert a grant title to a Drupal-style URL slug."""
    slug = title.lower().strip()
    slug = re.sub(r"[''`]", "", slug)           # strip apostrophes
    slug = re.sub(r"[^a-z0-9\s-]", " ", slug)  # strip punctuation
    slug = re.sub(r"\s+", "-", slug).strip("-")
    return slug


def _infer_sectors(text: str) -> list[str]:
    text_lower = text.lower()
    sectors: list[str] = []
    for keyword, sector_list in DOMAIN_SECTOR_MAP.items():
        if keyword in text_lower:
            sectors.extend(s for s in sector_list if s not in sectors)
    return sectors or ["Research & Innovation"]


def _fetch_page(session: requests.Session, url: str,
                params: dict | None = None) -> str | None:
    try:
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _parse_opportunities_from_html(html_text: str) -> list[dict]:
    """
    Extract NSERC funding opportunities from the listing HTML.

    The Drupal listing uses article cards with anchor-linked titles.
    Falls back to constructing URLs from title slugs if no anchor found.
    """
    opps: list[dict] = []

    # Primary pattern: anchor links to individual opportunity pages
    link_pat = re.compile(
        r'<a\s[^>]*href="(/en/funding/funding-opportunity/[^"?#]+)"[^>]*>'
        r'(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    seen_urls: set[str] = set()
    found_via_links = False

    for m in link_pat.finditer(html_text):
        href_raw  = m.group(1).strip()
        title_raw = _strip_tags(m.group(2)).strip()

        if not title_raw or len(title_raw) < 5:
            continue
        # Skip navigation / filter links
        if any(skip in href_raw for skip in [
            "field_fo_status", "field_audience", "field_inst_type",
            "field_program", "/page/",
        ]):
            continue

        url = f"{NSERC_BASE}{href_raw}"
        if url in seen_urls:
            continue
        seen_urls.add(url)
        found_via_links = True

        pos   = m.start()
        block = html_text[max(0, pos - 200): pos + 2000]

        # Deadline: look for explicit date patterns near this card
        deadline_iso = None
        deadline_raw = None
        date_pat = re.compile(
            r"(?:deadline|closing|due|closes?|apply by)[^<]{0,60}?"
            r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})",
            re.IGNORECASE,
        )
        dm = date_pat.search(block)
        if dm:
            deadline_raw = dm.group(1).strip()
            deadline_iso = _parse_date(deadline_raw)

        desc_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL | re.IGNORECASE)
        description = _strip_tags(desc_m.group(1)).strip()[:400] if desc_m else None

        opps.append({
            "title":       title_raw,
            "url":         url,
            "deadline_iso": deadline_iso,
            "deadline_raw": deadline_raw,
            "description": description,
        })

    if found_via_links:
        return opps

    # ---------------------------------------------------------------------------
    # Fallback: parse headings + "Open" status text and construct URLs from slugs
    # (used when Drupal renders titles without anchor links)
    # ---------------------------------------------------------------------------
    print("  NSERC: no anchor links found — using heading-based fallback parser")

    # Match <h2> or <h3> headings followed by "Open" status
    heading_pat = re.compile(
        r"<h[23][^>]*>\s*(.*?)\s*</h[23]>",
        re.DOTALL | re.IGNORECASE,
    )
    for m in heading_pat.finditer(html_text):
        title_raw = _strip_tags(m.group(1)).strip()
        if not title_raw or len(title_raw) < 5:
            continue

        # Only keep "Open" opportunities (check the 500-char block after the heading)
        pos   = m.start()
        block = html_text[pos: pos + 1000]
        if "open" not in block[:200].lower():
            continue

        slug = _title_to_slug(title_raw)
        if not slug:
            continue
        url = f"{NSERC_BASE}/en/funding/funding-opportunity/{slug}"
        if url in seen_urls:
            continue
        seen_urls.add(url)

        deadline_iso = None
        deadline_raw = None
        date_pat = re.compile(
            r"(?:deadline|closing|due|closes?|apply by)[^<]{0,60}?"
            r"(\d{4}-\d{2}-\d{2}|\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{1,2},?\s+\d{4})",
            re.IGNORECASE,
        )
        dm = date_pat.search(block)
        if dm:
            deadline_raw = dm.group(1).strip()
            deadline_iso = _parse_date(deadline_raw)

        desc_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL | re.IGNORECASE)
        description = _strip_tags(desc_m.group(1)).strip()[:400] if desc_m else None

        opps.append({
            "title":       title_raw,
            "url":         url,
            "deadline_iso": deadline_iso,
            "deadline_raw": deadline_raw,
            "description": description,
        })

    return opps


def _fetch_nserc_opportunities() -> list[dict]:
    session = requests.Session()
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,*/*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-CA,en;q=0.9",
    })

    all_opps: list[dict] = []

    for page_num in range(0, MAX_PAGES):
        params: dict = {"field_fo_status[open]": "open"}
        if page_num > 0:
            params["page"] = page_num

        html_text = _fetch_page(session, NSERC_LIST_URL, params=params)
        if not html_text:
            print(f"  NSERC: page {page_num} returned no content — stopping.")
            break

        if page_num == 0:
            idx = html_text.find("/en/funding/funding-opportunity/")
            if idx > 0:
                print(f"  NSERC: first opportunity link at char {idx} ✓")
            else:
                # Check for heading-based content
                idx2 = html_text.find("funding-opportunity")
                print(f"  NSERC: no opportunity hrefs on page 0 (first 'funding-opportunity' at {idx2})")
                print(f"  NSERC page 0 length: {len(html_text)} chars")

        page_opps = _parse_opportunities_from_html(html_text)
        if not page_opps:
            print(f"  NSERC: page {page_num} yielded 0 opportunities — stopping.")
            break

        existing_urls = {o["url"] for o in all_opps}
        new_opps = [o for o in page_opps if o["url"] not in existing_urls]
        all_opps.extend(new_opps)
        print(f"  NSERC page {page_num}: {len(new_opps)} new opportunities (total: {len(all_opps)})")

        # Stop if this page has fewer results than expected (last page)
        if len(new_opps) < 10:
            break

        time.sleep(0.5)

    return all_opps


def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url   = opp.get("url", "").strip()
    if not title or not url:
        return None

    return {
        "grant_title":              title,
        "funder_name":              "Natural Sciences and Engineering Research Council of Canada",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              opp.get("description"),
        "application_deadline":     opp.get("deadline_iso"),
        "application_deadline_raw": opp.get("deadline_raw"),
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         _infer_sectors(
            (title or "") + " " + (opp.get("description") or "")
        ),
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["CA"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_nserc_canada",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{url}|{title}".encode()
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
    parser = argparse.ArgumentParser(description="NSERC Canada → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching NSERC open funding opportunities …")
    raw_opps = _fetch_nserc_opportunities()
    print(f"  {len(raw_opps)} raw records scraped.")

    mapped = [_map_opportunity(o) for o in raw_opps]
    mapped = [g for g in mapped if g and g.get("source_url") and g.get("grant_title")]

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
