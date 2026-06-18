#!/usr/bin/env python3
"""
GrantGlobe — CIHR (Canadian Institutes of Health Research) connector.

The ResearchNet portal login page publicly displays the current open
competitions table (title, LOI deadline, application deadline) without
requiring authentication.

Source:
    https://www.researchnet-recherchenet.ca/rnr16/LoginServlet?language=E

Each row in the table links to a detail page (vwOpprtntyDtls.do?prog=NNNN)
which is also publicly accessible and contains the full program description.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/cihr_canada.py [--dry-run]
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

RESEARCHNET_BASE  = "https://www.researchnet-recherchenet.ca"
RESEARCHNET_LOGIN = f"{RESEARCHNET_BASE}/rnr16/LoginServlet?language=E"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-CA,en;q=0.9",
}

# Grant type prefixes → internal type tags
GRANT_TYPE_MAP = {
    "team grant":       ["Research Grant"],
    "operating grant":  ["Research Grant"],
    "catalyst grant":   ["Research Grant"],
    "project grant":    ["Research Grant"],
    "foundation grant": ["Research Grant"],
    "salary award":     ["Fellowship"],
    "fellowship":       ["Fellowship"],
    "undergraduate":    ["Scholarship"],
    "training":         ["Training Grant"],
    "planning":         ["Research Grant"],
    "knowledge":        ["Research Grant"],
    "other":            ["Grant"],
    "partnership":      ["Research Grant"],
}

# Thematic sectors from title keywords
SECTOR_KEYWORDS = {
    "mental health":   "Health Sciences",
    "cancer":          "Health Sciences",
    "aging":           "Health Sciences",
    "dementia":        "Health Sciences",
    "brain":           "Health Sciences",
    "infectious":      "Health Sciences",
    "influenza":       "Health Sciences",
    "antimicrobial":   "Health Sciences",
    "nutrition":       "Health Sciences",
    "food":            "Agriculture & Food",
    "child":           "Health Sciences",
    "youth":           "Health Sciences",
    "implementation":  "Health Sciences",
    "data":            "Research & Innovation",
    "clinical":        "Health Sciences",
    "community":       "Health Sciences",
}


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    html = re.sub(r'&lt;',  '<', html)
    html = re.sub(r'&gt;',  '>', html)
    html = re.sub(r'&#x27;', "'", html)
    html = re.sub(r'&ccedil;', 'ç', html)
    return re.sub(r'\s+', ' ', html).strip()


def _fetch(url: str, session: requests.Session) -> str:
    resp = session.get(url, headers=HEADERS, timeout=20, verify=False)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


def _parse_date(text: str) -> datetime.date | None:
    text = text.strip()
    try:
        return datetime.datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        return None


def _infer_grant_types(title: str) -> list[str]:
    tl = title.lower()
    for prefix, types in GRANT_TYPE_MAP.items():
        if tl.startswith(prefix):
            return types
    return ["Research Grant"]


def _infer_sectors(title: str, desc: str) -> list[str]:
    combined = (title + " " + desc).lower()
    sectors = []
    for kw, sector in SECTOR_KEYWORDS.items():
        if kw in combined and sector not in sectors:
            sectors.append(sector)
    return sectors or ["Health Sciences"]


# ── login page parser ─────────────────────────────────────────────────────────

def _parse_login_page(html: str) -> list[dict]:
    """
    Extract competition rows from the open competitions table on the login page.

    Table structure (simplified):
      <thead> ... Registration/LOI Deadline ... Application Deadline ... </thead>
      <tbody>
        <tr>
          <td><a href='...vwOpprtntyDtls.do?prog=NNNN...'>Title</a></td>
          <td>YYYY-MM-DD   (or <abbr>N/A</abbr>)</td>
          <td>YYYY-MM-DD   (or <abbr>N/A</abbr>)</td>
        </tr>
        ...
      </tbody>

    We parse <tr> blocks containing the competition link, then extract the
    three <td> cells per row (title+URL, LOI deadline, application deadline).
    Stripping tags before date parsing handles <abbr>N/A</abbr> cleanly.
    """
    today   = datetime.date.today()
    results = []

    tr_pat = re.compile(r'<tr[^>]*>(.*?)</tr>', re.DOTALL | re.IGNORECASE)
    td_pat = re.compile(r'<td[^>]*>(.*?)</td>', re.DOTALL | re.IGNORECASE)

    for tr_m in tr_pat.finditer(html):
        row_html = tr_m.group(1)

        # Only process rows that contain a competition detail link
        if 'vwOpprtntyDtls.do' not in row_html:
            continue

        cells = td_pat.findall(row_html)
        if len(cells) < 3:
            continue

        # Cell 0: title + URL
        href_m = re.search(r"href='([^']+vwOpprtntyDtls\.do[^']*)'", cells[0])
        if not href_m:
            continue
        url   = href_m.group(1).strip()
        title = _strip_tags(cells[0]).strip()
        if not title or len(title) < 5:
            continue

        # Cell 1: Registration/LOI deadline (often N/A — strip tags first)
        loi_text = _strip_tags(cells[1]).strip()
        loi_date = _parse_date(loi_text) if re.match(r'\d{4}-\d{2}-\d{2}', loi_text) else None

        # Cell 2: Application deadline
        app_text = _strip_tags(cells[2]).strip()
        app_date = _parse_date(app_text) if re.match(r'\d{4}-\d{2}-\d{2}', app_text) else None

        # Skip if application deadline has passed
        if app_date and app_date < today:
            continue

        # Ensure URL is canonical (www prefix)
        if url.startswith("https://researchnet"):
            url = url.replace("https://researchnet", "https://www.researchnet")

        results.append({
            "title":    title,
            "url":      url,
            "loi_date": loi_date,
            "app_date": app_date,
            "loi_raw":  loi_text if loi_date else None,
            "app_raw":  app_text if app_date else None,
        })

    # Deduplicate by URL
    seen: set[str] = set()
    unique = []
    for item in results:
        if item["url"] not in seen:
            seen.add(item["url"])
            unique.append(item)
    return unique


# ── detail page fetcher ───────────────────────────────────────────────────────

def _fetch_description(url: str, session: requests.Session) -> str:
    """
    Try to fetch the competition detail page for a description paragraph.
    Returns empty string if the page requires login or is otherwise inaccessible.
    """
    try:
        html = _fetch(url, session)
        # Look for meaningful <p> text after the title area
        paras = re.findall(r'<p[^>]*>(.*?)</p>', html, re.DOTALL | re.IGNORECASE)
        skip_kw = ['login', 'javascript', 'cookie', 'gov.ca', 'sign in',
                   'password', 'researchnet', 'contact us', 'mailto']
        for p in paras:
            text = _strip_tags(p).strip()
            if len(text) < 80:
                continue
            if any(kw in text.lower() for kw in skip_kw):
                continue
            return text[:500]
    except Exception:
        pass
    return ""


# ── record builder ────────────────────────────────────────────────────────────

def _build_record(item: dict, desc: str) -> dict:
    today = datetime.date.today()
    title = item["title"]
    url   = item["url"]
    app_date = item["app_date"]

    grant_types = _infer_grant_types(title)
    sectors     = _infer_sectors(title, desc)

    raw_str = f"{url}|{app_date.isoformat() if app_date else ''}"
    h       = hashlib.sha256(raw_str.encode()).hexdigest()

    return {
        "grant_title":              title,
        "funder_name":              "Canadian Institutes of Health Research (CIHR)",
        "source_url":               url,
        "application_portal_url":   RESEARCHNET_LOGIN,
        "description":              desc[:500] or None,
        "application_deadline":     app_date.isoformat() if app_date else None,
        "application_deadline_raw": item.get("app_raw") or None,
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         sectors,
        "grant_types":              grant_types,
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["CA"],
        "geographic_focus_countries": ["CA"],
        "organisation_types":       ["University", "Research Institution", "Hospital", "Non-profit"],
        "individual_eligibility":   [],
        "domain":                   "api_cihr",
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
                crawl_date = %s, content_hash = %s
               WHERE source_url = %s""",
            (
                record["grant_title"], record["description"],
                record["application_deadline"], record["application_deadline_raw"],
                record["crawl_date"], record["content_hash"],
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
    parser = argparse.ArgumentParser(description="CIHR Canada connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    parser.add_argument("--skip-details", action="store_true",
                        help="Skip fetching detail pages (faster, no descriptions)")
    args = parser.parse_args()

    requests.packages.urllib3.disable_warnings()
    session = requests.Session()

    print("Fetching CIHR open competitions from ResearchNet …")
    try:
        html = _fetch(RESEARCHNET_LOGIN, session)
    except Exception as e:
        print(f"ERROR: could not fetch login page — {e}", file=sys.stderr)
        sys.exit(1)

    competitions = _parse_login_page(html)
    print(f"  Found {len(competitions)} open competitions with future deadlines")

    records = []
    for i, item in enumerate(competitions, 1):
        desc = ""
        if not args.skip_details:
            desc = _fetch_description(item["url"], session)
            time.sleep(0.3)

        rec = _build_record(item, desc)
        records.append(rec)
        deadline_str = item["app_date"].isoformat() if item["app_date"] else "no deadline"
        print(f"  [{i:2d}] {item['title'][:70]} → {deadline_str}")

    print(f"\n  Total: {len(records)} records to upsert")

    if args.dry_run:
        print("\n[DRY RUN] First 3 records:")
        for r in records[:3]:
            print(json.dumps(r, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(records)} records.")
        return

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    inserted = updated = err = 0
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
            print(f"  DB error [{record['source_url'][:60]}]: {e}")
            err += 1

    conn.close()
    print(f"\nDone: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
