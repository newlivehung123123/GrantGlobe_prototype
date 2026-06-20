#!/usr/bin/env python3
"""
GrantGlobe — USDA NIFA (National Institute of Food and Agriculture) connector.

Fetches competitive grant programs from NIFA's NOFO list by:
  1. Scraping the NOFO listing page for all /grants/funding-opportunities/ links
  2. Visiting each detail page and extracting title, description, deadline, amounts

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/usda_nifa.py [--dry-run]
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

NIFA_BASE    = "https://www.nifa.usda.gov"
NIFA_LISTING = f"{NIFA_BASE}/grants/request-for-application-list-rfa"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

TOPIC_SECTOR_MAP = {
    "advanced technologies":     "Technology & Innovation",
    "animals":                   "Agriculture & Food",
    "plants":                    "Agriculture & Food",
    "food":                      "Agriculture & Food",
    "nutrition":                 "Health Sciences",
    "health":                    "Health Sciences",
    "environment":               "Climate & Environment",
    "natural resources":         "Climate & Environment",
    "bioenergy":                 "Climate & Environment",
    "education":                 "Education & Training",
    "economics":                 "Agriculture & Food",
    "rural communities":         "Agriculture & Food",
    "human sciences":            "Social Sciences & Humanities",
    "community vitality":        "Social Sciences & Humanities",
}

# Field-name tokens that immediately follow a metadata value — used to truncate
_NIFA_FIELD_NAMES = [
    "Contact for Electronic", "For more Information", "Funding Opportunity Number",
    "Assistance Listing", "Estimated Total", "Cost Sharing", "Range of Awards",
    "Topics", "Programs", "Eligibility", "Posted Date", "Page last updated",
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    """Strip tags; preserve newlines at block-element boundaries."""
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>',  ' ', html, flags=re.DOTALL | re.IGNORECASE)
    # Block-level closers → newline so field values don't bleed into adjacent labels
    html = re.sub(r'</(?:p|div|dt|dd|tr|li|h[1-6]|section|article)[^>]*>',
                  '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<br\s*/?>',  '\n', html, flags=re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    html = re.sub(r'&lt;', '<', html)
    html = re.sub(r'&gt;', '>', html)
    # Collapse horizontal whitespace only; preserve newlines
    html = re.sub(r'[^\S\n]+', ' ', html)
    return html.strip()


def _parse_date(text: str) -> datetime.date | None:
    """Parse dates like 'Thursday, December 31, 2026' or '2026-12-31'."""
    text = re.sub(r'^[A-Za-z]+,\s*', '', text.strip())  # strip day-of-week
    text = re.sub(r',?\s*\d{1,2}:\d{2}.*', '', text).strip()  # strip time
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d", "%d %B %Y", "%m/%d/%Y"):
        try:
            d = datetime.datetime.strptime(text, fmt).date()
            if d < datetime.date.today() - datetime.timedelta(days=730):
                return None
            return d
        except ValueError:
            continue
    return None


def _parse_amount(text: str) -> int | None:
    """Parse dollar amounts like '$300,000,000' into integer."""
    m = re.search(r'\$([\d,]+(?:\.\d+)?)\s*(?:million|M\b)?', text, re.IGNORECASE)
    if not m:
        return None
    num_str = m.group(1).replace(',', '')
    try:
        val = float(num_str)
        suffix = text[m.end():m.end() + 8].lower()
        if 'million' in suffix or re.match(r'\s*M\b', suffix):
            val *= 1_000_000
        return int(val)
    except ValueError:
        return None


def _infer_sectors(topics: list[str], title: str, desc: str) -> list[str]:
    combined = " ".join(topics + [title, desc]).lower()
    sectors: list[str] = []
    for keyword, sector in TOPIC_SECTOR_MAP.items():
        if keyword in combined and sector not in sectors:
            sectors.append(sector)
    return sectors or ["Research & Innovation"]


def _truncate_at_field(raw: str) -> str:
    """Remove trailing NIFA field labels that follow a value on the same line."""
    for tok in _NIFA_FIELD_NAMES:
        idx = raw.find(tok)
        if idx > 0:
            raw = raw[:idx]
    return raw.strip()


def _fetch(url: str, session: requests.Session) -> str:
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


# ── scraping ──────────────────────────────────────────────────────────────────

def _get_detail_urls(session: requests.Session) -> list[str]:
    """Parse all /grants/funding-opportunities/ links from the NOFO listing."""
    html = _fetch(NIFA_LISTING, session)
    slugs = list(dict.fromkeys(
        re.findall(r'href="(/grants/funding-opportunities/[a-z0-9][a-z0-9\-]+)"', html)
    ))
    urls = [NIFA_BASE + s for s in slugs]
    print(f"  NIFA: {len(urls)} NOFO links found")
    return urls


def _parse_detail(url: str, session: requests.Session) -> dict | None:
    """Fetch and parse a single NIFA NOFO detail page."""
    try:
        page_html = _fetch(url, session)
    except Exception as e:
        print(f"  NIFA: fetch error {url}: {e}")
        return None

    # ── title ─────────────────────────────────────────────────────────────────
    title = ""
    tm = re.search(r'<h1[^>]*>(.*?)</h1>', page_html, re.DOTALL | re.IGNORECASE)
    if tm:
        title = html.unescape(_strip_tags(tm.group(1)).strip())
    if not title:
        tm2 = re.search(r'<title>(.*?)</title>', page_html, re.DOTALL | re.IGNORECASE)
        if tm2:
            title = html.unescape(_strip_tags(tm2.group(1)).split('|')[0].strip())
    if not title or len(title) < 5:
        return None

    # ── content area: everything after the closing </h1> ─────────────────────
    h1_end = tm.end() if tm else 0
    after_h1 = page_html[h1_end:]

    # ── description ───────────────────────────────────────────────────────────
    desc = ""
    paras = re.findall(r'<p[^>]*>(.*?)</p>', after_h1, re.DOTALL | re.IGNORECASE)
    skip_kw = [
        '.gov means', 'federal government websites', 'sensitive information',
        'contact us', 'feedback', 'subscribe', 'consent', 'cookie',
        'please leave', 'skip to', 'reasonable accommodation',
        'language access', 'return to top', 'stay connected',
    ]
    for p in paras:
        candidate = _strip_tags(p).strip()
        if len(candidate) < 60:
            continue
        if any(kw in candidate.lower() for kw in skip_kw):
            continue
        desc = candidate[:500]
        break

    # ── structured metadata (newline-aware text) ──────────────────────────────
    text = _strip_tags(after_h1)

    # Closing Date
    deadline: datetime.date | None = None
    deadline_raw = ""
    cd_m = re.search(r'Closing Date\s*\n\s*([^\n]{8,80})', text)
    if cd_m:
        deadline_raw = _truncate_at_field(cd_m.group(1).strip())
        deadline = _parse_date(deadline_raw)
    # Fallback: same line (no newline in output)
    if not deadline_raw:
        cd_m2 = re.search(r'Closing Date\s+([A-Z][a-z]+(?:day)?,\s+[A-Z][a-z]+ \d+, \d{4})', text)
        if cd_m2:
            deadline_raw = cd_m2.group(1).strip()
            deadline = _parse_date(deadline_raw)

    # Posted Date
    posted_raw = ""
    pd_m = re.search(r'Posted Date\s*\n\s*([^\n]{8,60})', text)
    if pd_m:
        posted_raw = pd_m.group(1).strip()

    # Estimated Total Program Funding
    amount_max: int | None = None
    amount_raw = ""
    etpf_m = re.search(r'Estimated Total Program Funding\s*\n\s*(\$[\d,]+(?:\s*\w+)?)', text)
    if etpf_m:
        amount_raw = etpf_m.group(1).strip()
        amount_max = _parse_amount(amount_raw)

    # Range of Awards — minimum end
    amount_min: int | None = None
    roa_m = re.search(r'Range of Awards\s*\n\s*(\$[\d,]+)', text)
    if roa_m:
        amount_min = _parse_amount(roa_m.group(1))

    # Funding Opportunity Number
    fon_m = re.search(r'Funding Opportunity Number\s*\n\s*(\S+)', text)
    fon = fon_m.group(1).strip() if fon_m else ""

    # Topics (from topic links in full HTML)
    topics = re.findall(r'href="/topics/[^"]+">([^<]+)<', page_html)
    topics = [t.strip() for t in topics if len(t.strip()) > 2]

    return {
        "title":        title,
        "url":          url,
        "deadline":     deadline,
        "deadline_raw": deadline_raw,
        "posted_raw":   posted_raw,
        "amount_min":   amount_min,
        "amount_max":   amount_max,
        "amount_raw":   amount_raw,
        "description":  desc,
        "topics":       topics,
        "fon":          fon,
    }


# ── record builder ────────────────────────────────────────────────────────────

def _build_record(item: dict) -> dict:
    today    = datetime.date.today()
    deadline = item.get("deadline")
    sectors  = _infer_sectors(item.get("topics", []), item["title"], item.get("description", ""))

    raw_str = f"{item['title']}|{item.get('deadline_raw','')}|{item.get('fon','')}"
    h       = hashlib.sha256(raw_str.encode()).hexdigest()

    return {
        "grant_title":              item["title"],
        "funder_name":              "USDA National Institute of Food and Agriculture (NIFA)",
        "source_url":               item["url"],
        "application_portal_url":   item["url"],
        "description":              item.get("description", "")[:500] or None,
        "application_deadline":     deadline.isoformat() if deadline else None,
        "application_deadline_raw": item.get("deadline_raw") or None,
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       item.get("amount_min"),
        "funding_amount_max":       item.get("amount_max"),
        "currency":                 "USD" if (item.get("amount_min") or item.get("amount_max")) else None,
        "thematic_sectors":         sectors,
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution", "Non-profit"],
        "individual_eligibility":   [],
        "domain":                   "api_nifa",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             h,
    }


# ── DB upsert ─────────────────────────────────────────────────────────────────

def _upsert(conn, record: dict) -> str:
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s", (record["source_url"],))
    if cur.fetchone():
        cur.execute(
            """UPDATE grants SET
                grant_title = %s, description = %s,
                application_deadline = %s, application_deadline_raw = %s,
                funding_amount_min = %s, funding_amount_max = %s, currency = %s,
                crawl_date = %s, content_hash = %s
               WHERE source_url = %s""",
            (
                record["grant_title"], record["description"],
                record["application_deadline"], record["application_deadline_raw"],
                record["funding_amount_min"], record["funding_amount_max"],
                record["currency"], record["crawl_date"], record["content_hash"],
                record["source_url"],
            ),
        )
        return "updated"
    else:
        cols = list(record.keys())
        vals = [record[c] for c in cols]
        cur.execute(
            f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))})",
            vals,
        )
        return "inserted"


# ── main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="USDA NIFA connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    print("Fetching USDA NIFA NOFOs …")
    session = requests.Session()

    urls = _get_detail_urls(session)
    if not urls:
        print("  NIFA: no NOFO links found; aborting.")
        sys.exit(1)

    items   = []
    skipped = 0
    for i, url in enumerate(urls, 1):
        item = _parse_detail(url, session)
        if item:
            items.append(item)
        else:
            skipped += 1
        if i % 10 == 0:
            print(f"  NIFA: {i}/{len(urls)} fetched …")
        time.sleep(0.3)

    print(f"  NIFA: {len(items)} NOFOs parsed ({skipped} skipped)")

    records = [_build_record(i) for i in items]

    if args.dry_run:
        print(f"\n[DRY RUN] First 3 records:")
        for r in records[:3]:
            print(json.dumps(r, indent=2, default=str))
        # Also show one with a non-null deadline if any
        deadline_records = [r for r in records if r.get("application_deadline")]
        print(f"\n[DRY RUN] {len(deadline_records)} records have a future deadline.")
        if deadline_records:
            print("Sample with deadline:")
            print(json.dumps(deadline_records[0], indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(records)} records.")
        return

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    inserted = updated = err = skipped_dupe = 0
    for record in records:
        try:
            result = _upsert(conn, record)
            conn.commit()
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            conn.rollback()
            if "grants_content_hash_key" in str(e):
                # Harmless duplicate: NIFA listed the same NOFO under two
                # detail URLs with identical title/deadline_raw/FON, so the
                # source_url lookup missed the existing row and we tried to
                # INSERT a second copy. Not a real failure.
                skipped_dupe += 1
            else:
                print(f"  DB error {record['source_url']}: {e}")
                err += 1

    conn.close()
    print(f"\nDone: {inserted} inserted, {updated} updated, "
          f"{skipped_dupe} skipped (duplicate), {err} errors.")


if __name__ == "__main__":
    main()
