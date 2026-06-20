#!/usr/bin/env python3
"""
Wellcome connector.

Wellcome is one of the world's largest biomedical research funders (~£1B/year),
supporting research across life sciences, health, medicine, and the humanities
of health at organisations globally.

Active grant schemes covered:
  - Wellcome Early-Career Awards     (salary + up to £400k; ~5 years; ~3 rounds/yr)
  - Wellcome Career Development Awards (mid-career; up to £2M/8yr; ~3 rounds/yr)
  - Wellcome Discovery Awards          (established researchers; ~£3.5M/8yr; ~3/yr)

Closed/inactive schemes (excluded):
  - Investigator Awards in Science → closed (superseded by Discovery Awards)
  - Collaborative Awards in Science → closed

Deadline source:
  The page https://wellcome.org/research-funding/guidance/prepare-to-apply/
  scheme-application-deadlines is server-rendered and contains a pipe-separated
  table of all upcoming scheme deadlines. This connector fetches it and parses
  the next future full-application deadline for each scheme. If the page does not
  yet list a future round (it is typically updated ~6–8 weeks before opening),
  the connector falls back to a pattern-estimated date and marks the record
  "Forthcoming".

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/wellcome.py [--dry-run]
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

FUNDER        = "Wellcome"
DOMAIN        = "api_wellcome"
BASE          = "https://wellcome.org"
PORTAL        = "https://wellcome.org/grant-funding/apply"
DEADLINES_URL = (
    f"{BASE}/research-funding/guidance/prepare-to-apply/scheme-application-deadlines"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# Month pattern
_MONTHS = (
    r'(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
)
_DATE_PAT = rf'(?:\d{{1,2}}\s+{_MONTHS}\s+\d{{4}}|{_MONTHS}\s+\d{{1,2}},?\s+\d{{4}})'


# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------
# next_cycle: estimated fallback date if deadlines page doesn't list a future round
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "key":         "Wellcome Early-Career Awards",
        "title":       "Wellcome Early-Career Awards",
        "url":         f"{BASE}/grant-funding/schemes/early-career-awards",
        "next_cycle":  datetime.date(2026, 7, 22),   # confirmed: Jul 22, 2026
        "grant_types": ["Fellowship", "Research Grant"],
        "individual":  ["Early Career Researcher", "Postdoctoral Researcher"],
        "org_types":   ["University", "Research Institution"],
        "sectors":     ["Health Sciences", "Research & Innovation", "Science & Technology"],
        "desc": (
            "Wellcome Early-Career Awards fund researchers who are ready to develop "
            "their independent research identity, across any discipline with the potential "
            "to improve human life, health and wellbeing. Awards provide a personal salary "
            "plus up to £400,000 for research expenses, typically for 5 years. Applicants "
            "must have completed a PhD or equivalent and usually have no more than 3 years "
            "of postdoctoral experience. Host organisations must be based in the UK, Republic "
            "of Ireland, or a low/middle-income country. Applications are submitted via the "
            "Wellcome Funding Platform. The scheme runs approximately 3 rounds per year."
        ),
    },
    {
        "key":         "Wellcome Career Development Awards",
        "title":       "Wellcome Career Development Awards",
        "url":         f"{BASE}/research-funding/schemes/wellcome-career-development-awards",
        "next_cycle":  datetime.date(2026, 7, 28),   # confirmed: Jul 28, 2026
        "grant_types": ["Research Grant", "Fellowship"],
        "individual":  ["Mid-Career Researcher", "Faculty Researcher"],
        "org_types":   ["University", "Research Institution"],
        "sectors":     ["Health Sciences", "Research & Innovation", "Science & Technology"],
        "desc": (
            "Wellcome Career Development Awards support mid-career researchers who are "
            "ready to lead an ambitious, innovative research programme. Awards provide "
            "funding of up to around £2 million (salary is not included) for up to 8 years. "
            "Applicants should have an established research record and typically hold an "
            "independent research position. Host organisations must be in the UK, Republic "
            "of Ireland, or a low/middle-income country. Applications are submitted via the "
            "Wellcome Funding Platform. The scheme runs approximately 3 rounds per year."
        ),
    },
    {
        "key":         "Wellcome Discovery Awards",
        "title":       "Wellcome Discovery Awards",
        "url":         f"{BASE}/research-funding/schemes/wellcome-discovery-awards",
        "next_cycle":  datetime.date(2026, 9, 22),   # confirmed: Sep 22, 2026
        "grant_types": ["Research Grant"],
        "individual":  ["Faculty Researcher", "Senior Researcher"],
        "org_types":   ["University", "Research Institution"],
        "sectors":     ["Health Sciences", "Research & Innovation", "Science & Technology"],
        "desc": (
            "Wellcome Discovery Awards fund established researchers and teams pursuing bold, "
            "creative research ideas across any discipline that can improve human health and "
            "wellbeing. The average award is £3.5 million and awards can last up to 8 years. "
            "Applicants must hold an established, independent research position at a Wellcome-"
            "eligible organisation. Host organisations must be in the UK, Republic of Ireland, "
            "or a low/middle-income country. Applications are submitted via the Wellcome "
            "Funding Platform. The scheme runs approximately 3 rounds per year."
        ),
    },
]


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


def _fetch(url: str, timeout: int = 30) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _parse_date_str(text: str) -> datetime.date | None:
    text = re.sub(r'(\d+)(?:st|nd|rd|th)\b', r'\1', text.strip())
    text = re.sub(r'\s+', ' ', text)
    for fmt in (
        "%d %B %Y", "%d %b %Y",
        "%B %d, %Y", "%B %d %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Deadlines page parser
# ---------------------------------------------------------------------------

def _fetch_upcoming_deadlines(today: datetime.date) -> dict[str, datetime.date]:
    """
    Fetch the Wellcome scheme-application-deadlines page and return a dict
    mapping scheme name → next upcoming full-application deadline.
    """
    result: dict[str, datetime.date] = {}
    html = _fetch(DEADLINES_URL)
    if not html:
        return result

    # Strip HTML tags, collapse whitespace — page is server-rendered
    text = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'&nbsp;', ' ', text)
    text = re.sub(r'&amp;', '&', text)
    text = re.sub(r'\s+', ' ', text).strip()

    # Scheme names to search for in table rows
    targets = {
        "Wellcome Early-Career Awards":      "Wellcome Early-Career Awards",
        "Wellcome Career Development Awards": "Wellcome Career Development Awards",
        "Wellcome Discovery Awards":          "Wellcome Discovery Awards",
    }

    # The table rows look like:
    #   Wellcome Early-Career Awards | n/a | 17 February 2026 | July 2026 |
    # We want column 3 (full application date), the first one that's >= today.
    for key, label in targets.items():
        # Find all matches for this scheme in the text
        # Pattern: scheme label ... | date_col | date_col | date_col
        pat = re.escape(label) + r'.*?\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|'
        for m in re.finditer(pat, text, re.IGNORECASE | re.DOTALL):
            # col 2 = full application deadline, col 1 = preliminary (often n/a)
            full_app_raw = m.group(2).strip()
            d = _parse_date_str(full_app_raw)
            if d and d >= today:
                # Keep the earliest future date found
                if key not in result or d < result[key]:
                    result[key] = d

    return result


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(scheme: dict, deadline: datetime.date, status: str) -> dict:
    today = datetime.date.today()
    deadline_iso = deadline.isoformat()
    deadline_raw = str(deadline.day) + " " + deadline.strftime("%B %Y")

    return {
        "grant_title":              scheme["title"],
        "funder_name":              FUNDER,
        "source_url":               scheme["url"],
        "application_portal_url":   PORTAL,
        "description":              scheme["desc"],
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       None,
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         scheme["sectors"],
        "grant_types":              scheme["grant_types"],
        "applicant_base_regions":   ["Global"],
        "geographic_focus_regions": ["Global"],
        "applicant_base_countries": [],
        "geographic_focus_countries": [],
        "organisation_types":       scheme["org_types"],
        "individual_eligibility":   scheme["individual"],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(scheme["url"], scheme["title"], deadline_iso),
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM grants WHERE source_url = %s",
        (record["source_url"],)
    )
    existing = cur.fetchone()
    if existing:
        _upd_cols = [c for c in record if c != "source_url"]
        _set_clause = ", ".join(f"{c} = %({c})s" for c in _upd_cols)
        cur.execute(
            f"UPDATE grants SET {_set_clause} WHERE id = %(id)s",
            {**record, "id": existing[0]},
        )
        return "updated"
    cols = list(record.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        [record[c] for c in cols],
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Wellcome connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip live deadline fetch; use pattern dates only")
    args = parser.parse_args()

    today = datetime.date.today()
    records: list[dict] = []

    # Try to get live upcoming deadlines from Wellcome's deadlines page
    live_dates: dict[str, datetime.date] = {}
    if not args.skip_fetch:
        print("Fetching Wellcome scheme deadlines page …")
        live_dates = _fetch_upcoming_deadlines(today)
        if live_dates:
            print(f"  Found {len(live_dates)} live deadline(s): "
                  + ", ".join(f"{k.split()[-2]}: {v}" for k, v in live_dates.items()))
        else:
            print("  No upcoming deadlines on page — using pattern estimates.")
        time.sleep(1)

    for scheme in SCHEMES:
        key = scheme["key"]
        live = live_dates.get(key)

        if live and live >= today:
            deadline = live
            # Determine status: if deadline is within 30 days or confirmed open, use Open
            # Wellcome schemes open ~6-8 weeks before deadline; if within ~60 days → Open
            days_until = (deadline - today).days
            status = "Open" if days_until <= 60 else "Forthcoming"
        else:
            # Use fallback pattern estimate
            est = scheme["next_cycle"]
            if est < today:
                # Advance by ~4 months (typical inter-round gap) until future
                while est < today:
                    month = est.month + 4
                    year = est.year + (month - 1) // 12
                    month = ((month - 1) % 12) + 1
                    try:
                        est = est.replace(year=year, month=month)
                    except ValueError:
                        est = datetime.date(year, month, 28)
            deadline = est
            days_until = (deadline - today).days
            status = "Open" if days_until <= 60 else "Forthcoming"

        rec = _build_record(scheme, deadline, status)
        records.append(rec)
        src = "live" if live else "estimated"
        print(f"  [{status:12s}] {rec['grant_title'][:55]}  → {deadline}  ({src})")

    print(f"\n  Total: {len(records)} records")

    if args.dry_run:
        print("\n[DRY RUN] Full records:")
        for r in records:
            print(json.dumps(r, indent=2, default=str))
        return

    conn = _connect()
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
            print(f"  DB error [{record['grant_title'][:50]}]: {e}")
            err += 1
    conn.close()
    print(f"\nDone: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
