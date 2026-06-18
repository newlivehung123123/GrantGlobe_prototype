#!/usr/bin/env python3
"""
Australian Government grants connector — Stage 2 API source.

Scrapes the Australian Government Grants portal at grants.gov.au for
open funding opportunities. No API key required.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/australia.py [--dry-run]
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

AUS_BASE     = "https://www.grants.gov.au"
AUS_LIST_URL = "https://www.grants.gov.au/Go/List"
MAX_PAGES    = 30

CATEGORY_SECTOR_MAP: dict[str, list[str]] = {
    "health":          ["Health Sciences"],
    "medical":         ["Health Sciences"],
    "research":        ["Research & Innovation"],
    "education":       ["Education & Training"],
    "environment":     ["Climate & Environment"],
    "agriculture":     ["Agriculture & Food"],
    "food":            ["Agriculture & Food"],
    "community":       ["Social Services & Welfare"],
    "social":          ["Social Sciences & Humanities"],
    "innovation":      ["Technology & Innovation"],
    "technology":      ["Science & Technology", "Technology & Innovation"],
    "science":         ["Science & Technology"],
    "arts":            ["Arts & Culture"],
    "indigenous":      ["Social Services & Welfare"],
    "infrastructure":  ["Infrastructure & Urban Development"],
    "regional":        ["Economic Development"],
    "export":          ["Economic Development"],
    "business":        ["Economic Development"],
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
    # Remove time component
    date_str = re.sub(r"\s+\d+:\d+.*$", "", date_str).strip()
    for fmt in ("%d/%m/%Y", "%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _infer_sectors(text: str) -> list[str]:
    text_lower = text.lower()
    sectors: list[str] = []
    for keyword, sector_list in CATEGORY_SECTOR_MAP.items():
        if keyword in text_lower:
            sectors.extend(s for s in sector_list if s not in sectors)
    return sectors or ["Research & Innovation"]


def _fetch_page(session: requests.Session, url: str, params: dict | None = None) -> str | None:
    try:
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _parse_grants_from_html(html_text: str) -> list[dict]:
    """
    Extract grants from the grants.gov.au listing HTML.

    The listing page shows grant opportunities in a table or card list.
    Each row links to a detail page under /Go/Show?GoUuid=<uuid>.
    """
    opps: list[dict] = []

    # Primary pattern: links to grant detail pages with GoUuid
    uuid_pat = re.compile(
        r'<a\s[^>]*href="(/Go/Show\?GoUuid=[^"&]+|/Go/Show\?GoUuid=[^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    seen_urls: set[str] = set()
    for m in uuid_pat.finditer(html_text):
        href_raw  = m.group(1).strip()
        title_raw = _strip_tags(m.group(2)).strip()

        if not title_raw or len(title_raw) < 5:
            continue

        url = f"{AUS_BASE}{href_raw}" if href_raw.startswith("/") else href_raw
        if url in seen_urls:
            continue
        seen_urls.add(url)

        pos   = m.start()
        block = html_text[max(0, pos - 100): pos + 3000]

        # Extract deadline from table cells / metadata near this block
        deadline_raw = None
        deadline_iso = None
        date_patterns = [
            re.compile(
                r"(?:closing|close|deadline)[^<]{0,50}?"
                r"(\d{1,2}/\d{1,2}/\d{4}|\d{1,2}\s+\w+\s+\d{4})",
                re.IGNORECASE,
            ),
            re.compile(r"(\d{1,2}/\d{2}/\d{4})"),  # fallback: first date in block
        ]
        for dpat in date_patterns:
            dm = dpat.search(block)
            if dm:
                deadline_raw = dm.group(1)
                deadline_iso = _parse_date(deadline_raw)
                if deadline_iso:
                    break

        # Opening agency
        agency_m = re.search(
            r"(?:agency|department|administering)[^<]{0,30}?<[^>]+>([^<]{3,80})<",
            block, re.IGNORECASE,
        )
        agency_name = _strip_tags(agency_m.group(1)).strip() if agency_m else "Australian Government"

        desc_m = re.search(r"<p[^>]*>(.*?)</p>", block, re.DOTALL | re.IGNORECASE)
        description = _strip_tags(desc_m.group(1)).strip()[:400] if desc_m else None

        # Grant amount
        amt_m = re.search(
            r"\$\s*([\d,]+(?:\.\d+)?(?:\s*(?:million|m|k))?)",
            block, re.IGNORECASE,
        )
        funding_max = None
        if amt_m:
            amt_str = amt_m.group(1).replace(",", "").strip()
            try:
                val = float(re.sub(r"[^\d.]", "", amt_str.split()[0]))
                if "million" in amt_str.lower() or amt_str.lower().endswith("m"):
                    val *= 1_000_000
                elif amt_str.lower().endswith("k"):
                    val *= 1_000
                funding_max = val
            except (ValueError, TypeError):
                pass

        uuid_m = re.search(r"GoUuid=([A-Za-z0-9_-]+)", href_raw)
        opp_id = uuid_m.group(1) if uuid_m else href_raw

        opps.append({
            "title":            title_raw,
            "url":              url,
            "agency":           agency_name,
            "deadline_iso":     deadline_iso,
            "deadline_raw":     deadline_raw,
            "description":      description,
            "funding_max":      funding_max,
            "thematic_sectors": _infer_sectors((title_raw or "") + " " + (description or "")),
            "opp_id":           opp_id,
        })

    return opps


def _fetch_aus_opportunities() -> list[dict]:
    session = requests.Session()
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,*/*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-AU,en;q=0.9",
    })

    all_opps: list[dict] = []

    for page_num in range(1, MAX_PAGES + 1):
        params = {
            "GrantStatus": "Open",
            "Page": page_num,
        }
        html_text = _fetch_page(session, AUS_LIST_URL, params=params)
        if not html_text:
            print(f"  AUS: page {page_num} returned no content — stopping.")
            break

        if page_num == 1:
            idx = html_text.find("GoUuid")
            if idx > 0:
                print(f"  AUS: first GoUuid link found at char {idx} ✓")
            else:
                print("  AUS WARNING: no GoUuid links found on page 1 — check URL/params")
                # Print a slice of the HTML for diagnosis
                print(f"  AUS page 1 status: {html_text[:200]}")
                print(f"  AUS page 1 snippet (4000-5500): {html_text[4000:5500]}")

        page_opps = _parse_grants_from_html(html_text)
        if not page_opps:
            print(f"  AUS: page {page_num} yielded 0 opportunities — stopping.")
            break

        existing_urls = {o["url"] for o in all_opps}
        new_opps = [o for o in page_opps if o["url"] not in existing_urls]
        all_opps.extend(new_opps)
        print(f"  AUS page {page_num}: {len(new_opps)} new opportunities (total: {len(all_opps)})")

        # If last page returned fewer items than expected, stop
        if len(page_opps) < 5:
            break

        time.sleep(0.5)

    return all_opps


def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url   = opp.get("url", "").strip()
    if not title or not url:
        return None

    opp_id       = opp.get("opp_id") or url
    deadline_iso = opp.get("deadline_iso")
    funding_max  = opp.get("funding_max")

    return {
        "grant_title":              title,
        "funder_name":              opp.get("agency", "Australian Government"),
        "source_url":               url,
        "application_portal_url":   url,
        "description":              opp.get("description"),
        "application_deadline":     deadline_iso,
        "application_deadline_raw": opp.get("deadline_raw"),
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       funding_max,
        "currency":                 "AUD" if funding_max else None,
        "thematic_sectors":         opp.get("thematic_sectors", ["Research & Innovation"]),
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Asia-Pacific"],
        "geographic_focus_regions": ["Asia-Pacific"],
        "applicant_base_countries": ["AU"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_aus_grants",
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
    parser = argparse.ArgumentParser(description="Australian grants.gov.au → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching Australian Government open grants …")
    raw_opps = _fetch_aus_opportunities()
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
