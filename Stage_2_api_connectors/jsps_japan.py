#!/usr/bin/env python3
"""
GrantGlobe — JSPS Japan Postdoctoral Fellowship connector.

Fetches upcoming application deadlines for two open-call fellowship programs:
  - Standard Program (worldwide, 12-24 months)
  - Short-term Program PE (US/Canada/Europe, 1 week to 12 months)

Each recruitment round becomes one record (unique URL fragment).

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/jsps_japan.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

import psycopg2
import requests

JSPS_BASE = "https://www.jsps.go.jp"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Programme definitions — description and metadata are stable; only deadlines change
PROGRAMS = [
    {
        "code":            "jsps_standard",
        "grant_title_base": "JSPS Postdoctoral Fellowship for Research in Japan – Standard Program",
        "about_url":       "https://www.jsps.go.jp/english/e-ippan/index.html",
        "schedule_url":    "https://www.jsps.go.jp/english/e-fellow/e-ippan/appliguidelines.html",
        "description": (
            "The JSPS Standard Postdoctoral Fellowship provides opportunities for postdoctoral "
            "researchers from any country to conduct cooperative research under the guidance of "
            "leading research groups in Japanese universities and institutions for 12–24 months. "
            "Applications are submitted through a host researcher in Japan. Approximately 120 "
            "fellowships are awarded per recruitment round."
        ),
        "regions":    ["Asia Pacific"],
        "countries":  [],           # worldwide eligibility
        "org_types":  ["Individual"],
        "individual_eligibility": ["Postdoctoral Researcher"],
    },
    {
        "code":            "jsps_pe",
        "grant_title_base": "JSPS Postdoctoral Fellowship for Research in Japan – Short-term Program (PE)",
        "about_url":       "https://www.jsps.go.jp/english/e-oubei-s/index.html",
        "schedule_url":    "https://www.jsps.go.jp/english/e-fellow/e-oubei-s/appliguidelines.html",
        "description": (
            "The JSPS Short-term Postdoctoral Fellowship (PE) provides pre- and postdoctoral "
            "researchers from the United States, Canada, and Europe with opportunities to conduct "
            "cooperative research at leading Japanese research institutions for 1 week to 12 months. "
            "Applications must be submitted through a host researcher in Japan. Approximately 20 "
            "fellowships are awarded per recruitment round."
        ),
        "regions":    ["North America", "Europe"],
        "countries":  ["US", "CA", "GB", "DE", "FR", "NL", "SE", "CH", "AT", "BE",
                       "DK", "FI", "IT", "ES", "NO", "PL", "PT", "CZ", "HU", "IE"],
        "org_types":  ["Individual"],
        "individual_eligibility": ["Pre-doctoral Researcher", "Postdoctoral Researcher"],
    },
]


# ── helpers ───────────────────────────────────────────────────────────────────

def _strip_tags(html: str) -> str:
    html = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', html).strip()


def _parse_date(text: str) -> datetime.date | None:
    """Parse 'August 28, 2026' or 'August 28, 2026 (by 5 p.m. (JST))'."""
    # Truncate at first '(' — handles nested parens like "(by 5 p.m. (JST))"
    if '(' in text:
        text = text[:text.index('(')]
    text = re.sub(r',?\s*by\s+.*', '', text).strip()
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _fetch(url: str, session: requests.Session) -> str:
    resp = session.get(url, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


# ── schedule parsing ──────────────────────────────────────────────────────────

def _parse_schedule(html: str) -> list[dict]:
    """
    Extract future recruitment rounds from a JSPS application schedule page.

    The page is organised into sections headed by <h3>FY20XX</h3>.
    Each section contains a table with columns:
      Recruitment | Application deadline | Selection results | Arrival periods | # fellowships

    We parse FY directly from the section heading (more reliable than
    inferring it from the deadline date), and only include rounds whose
    deadline is strictly today or later.

    Returns list of dicts: {fy, recruitment, deadline, deadline_raw, count}.
    """
    today  = datetime.date.today()
    rounds: list[dict] = []

    # Split into FY sections using h2-h4 headings that contain "FY20XX"
    fy_pat = re.compile(r'<h[2-4][^>]*>[^<]*FY(20\d{2})[^<]*</h[2-4]>', re.IGNORECASE)
    section_starts = [(int(m.group(1)), m.end()) for m in fy_pat.finditer(html)]

    if not section_starts:
        return rounds  # page structure unexpected

    # Add sentinel for end of last section
    section_starts.append((None, len(html)))

    for i, (fy, start) in enumerate(section_starts[:-1]):
        section_html = html[start:section_starts[i + 1][1]]

        rows = re.findall(r'<tr[^>]*>(.*?)</tr>', section_html, re.DOTALL | re.IGNORECASE)
        for row in rows:
            cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.DOTALL | re.IGNORECASE)
            if len(cells) < 4:
                continue

            recruitment = _strip_tags(cells[0]).strip()   # e.g. "1st"
            deadline_raw = _strip_tags(cells[1]).strip()  # e.g. "August 28, 2026 (by 5 p.m. (JST))"
            count_raw    = _strip_tags(cells[4]).strip() if len(cells) > 4 else ""

            if not deadline_raw or not re.search(r'\d{4}', deadline_raw):
                continue

            deadline = _parse_date(deadline_raw)
            if deadline is None or deadline < today:  # strict: no grace window
                continue

            count_m = re.search(r'(\d+)', count_raw)
            count   = int(count_m.group(1)) if count_m else None

            rounds.append({
                "fy":          fy,
                "recruitment": recruitment,
                "deadline":    deadline,
                "deadline_raw": deadline_raw,
                "count":       count,
            })

    return rounds


# ── record builder ────────────────────────────────────────────────────────────

def _build_record(prog: dict, rnd: dict) -> dict:
    today    = datetime.date.today()
    deadline = rnd["deadline"]
    fy       = rnd["fy"]  # from section heading, not computed from deadline year
    title = f"{prog['grant_title_base']} (FY{fy}, {rnd['recruitment']} Recruitment)"
    # Unique URL fragment: strip ordinal suffix (st/nd/rd/th) cleanly
    num = re.sub(r'(?:st|nd|rd|th)$', '', rnd['recruitment'].lower())
    url = f"{prog['about_url']}#fy{fy}-r{num}"

    raw_str = f"{prog['code']}|fy{fy}|{num}|{deadline.isoformat()}"
    h       = hashlib.sha256(raw_str.encode()).hexdigest()

    desc = prog["description"]
    if rnd.get("count"):
        desc = f"[{rnd['count']} fellowships per round] " + desc

    return {
        "grant_title":              title,
        "funder_name":              "Japan Society for the Promotion of Science (JSPS)",
        "source_url":               url,
        "application_portal_url":   prog["schedule_url"],
        "description":              desc[:500],
        "application_deadline":     deadline.isoformat(),
        "application_deadline_raw": rnd["deadline_raw"],
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         ["Research & Innovation"],
        "grant_types":              ["Fellowship"],
        "applicant_base_regions":   prog["regions"],
        "geographic_focus_regions": ["Asia Pacific"],
        "applicant_base_countries": prog["countries"],
        "geographic_focus_countries": ["JP"],
        "organisation_types":       prog["org_types"],
        "individual_eligibility":   prog["individual_eligibility"],
        "domain":                   "api_jsps",
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
    parser = argparse.ArgumentParser(description="JSPS Japan fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    print("Fetching JSPS fellowship schedules …")
    session  = requests.Session()
    records: list[dict] = []

    for prog in PROGRAMS:
        print(f"  Fetching: {prog['grant_title_base']}")
        try:
            html = _fetch(prog["schedule_url"], session)
        except Exception as e:
            print(f"  ERROR: {e}")
            continue

        rounds = _parse_schedule(html)
        print(f"    → {len(rounds)} upcoming rounds found")
        for rnd in rounds:
            records.append(_build_record(prog, rnd))
            print(f"      {rnd['recruitment']}: {rnd['deadline']} ({rnd.get('count','?')} fellowships)")

    print(f"\n  Total: {len(records)} records to upsert")

    if args.dry_run:
        print(f"\n[DRY RUN] Records:")
        for r in records:
            print(json.dumps(r, indent=2, default=str))
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
            print(f"  DB error {record['source_url']}: {e}")
            err += 1

    conn.close()
    print(f"\nDone: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
