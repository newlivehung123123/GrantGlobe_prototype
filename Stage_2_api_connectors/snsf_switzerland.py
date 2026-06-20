#!/usr/bin/env python3
"""
Swiss National Science Foundation (SNSF) connector.

The SNSF is Switzerland's primary research funding agency, distributing
more than CHF 1 billion annually across all disciplines. It funds basic
research at Swiss universities and research institutions.

Scheme pages on snf.ch are fully server-rendered (no JS required) and
contain the current submission deadline in DD.MM.YYYY format near the top
of each page. This connector fetches each scheme page live and parses the
upcoming deadline directly from the page content.

Schemes covered:
  - SNSF Project Funding (biannual: 1 April and 1 October each year)
  - SNSF Postdoc.Mobility (biannual: ~February and August; final call Aug 2027)
  - SNSF Ambizione (annual: ~November; final call Nov 2026)

Closed / excluded schemes:
  - SNSF Starting Grants: most recent call May 2026 (closed); next cycle TBD
  - Eccellenza: professorships for women, irregular schedule
  - Weave/Lead Agency/ICIS: co-funded with international partner agencies

Eligibility note: SNSF grants are primarily for researchers based at Swiss
higher education institutions (or closely linked to Switzerland). The
applicant_base_countries field reflects this constraint.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/snsf_switzerland.py [--dry-run]
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

FUNDER  = "Swiss National Science Foundation (SNSF)"
DOMAIN  = "api_snsf"
BASE    = "https://www.snf.ch"
PORTAL_MYSNF   = "https://www.mysnf.ch/login.aspx"
PORTAL_SNFPORTAL = "https://portal.snf.ch/core/landing-page"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# Date patterns
_MONTHS = (
    r'(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
)

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "SNSF Project Funding",
        "url":      f"{BASE}/en/WAvYcY7awAUGolST/funding/projects/project-funding",
        "portal":   PORTAL_SNFPORTAL,
        "fallback_next": datetime.date(2026, 10, 1),   # biannual: Apr 1 and Oct 1
        "biannual_months": (4, 10),                    # April and October
        "biannual_day": 1,
        "open_threshold_days": 60,
        "final_call": None,
        "grant_types":  ["Research Grant"],
        "individual":   ["Faculty Researcher", "Senior Researcher", "Mid-Career Researcher"],
        "org_types":    ["University", "Research Institution"],
        "sectors":      ["Research & Innovation", "Science & Technology", "Health Sciences",
                         "Social Sciences & Humanities"],
        "desc": (
            "SNSF Project Funding is Switzerland's largest research funding scheme, investing "
            "over CHF 500 million annually in new projects across all disciplines. Researchers "
            "can apply individually or as a collaborative team to study topics of their own "
            "choosing, with grants of up to CHF 250,000 per applicant per year (minimum CHF "
            "100,000; minimum duration one year; maximum four years). Staff salaries and "
            "research costs are covered; the applicant's own salary is paid by their institution. "
            "Applicants must be based at an SNSF-eligible Swiss research institution and hold a "
            "doctorate obtained at least four years before the submission date. Collaborative "
            "projects with three or more applicants are capped at CHF 3 million total. "
            "Applications are submitted via the SNSF Portal. Submission deadlines are 1 April "
            "and 1 October each year at 17:00 Swiss local time."
        ),
    },
    {
        "title":    "SNSF Postdoc.Mobility",
        "url":      f"{BASE}/en/XIZpfY3iVS5KRRoD/funding/careers/postdoc-mobility",
        "portal":   PORTAL_MYSNF,
        "fallback_next": datetime.date(2026, 8, 4),    # confirmed: Aug 4, 2026
        "biannual_months": (2, 8),                     # February and August
        "biannual_day": 4,
        "open_threshold_days": 80,
        "final_call": "The final Postdoc.Mobility call is August 2027; a new postdoctoral "
                      "funding scheme will be launched in 2028.",
        "grant_types":  ["Fellowship"],
        "individual":   ["Postdoctoral Researcher"],
        "org_types":    ["University", "Research Institution"],
        "sectors":      ["Research & Innovation", "Science & Technology", "Health Sciences",
                         "Social Sciences & Humanities"],
        "desc": (
            "SNSF Postdoc.Mobility fellowships support early-career Swiss researchers — or "
            "researchers closely linked to Switzerland — in conducting a research stay abroad to "
            "gain in-depth knowledge, extend their scientific network, and enhance their research "
            "profile in view of an academic career in Switzerland. Fellows receive a subsistence "
            "grant, flat-rate travel allowance, and a contribution to research and conference "
            "costs for a 24-month stay, followed by an optional 3–12 month return grant. "
            "Applicants must hold a PhD (or be within 6 months of completing one) and meet "
            "Swiss citizenship, residency, or education-link requirements. Applications are "
            "submitted via mySNF. Note: this scheme is being wound down; the final call "
            "is August 2027, with a new postdoctoral scheme launching in 2028."
        ),
    },
    {
        "title":    "SNSF Ambizione",
        "url":      f"{BASE}/en/N18L3oGWomTSSGkF/funding/careers/ambizione",
        "portal":   PORTAL_MYSNF,
        "fallback_next": datetime.date(2026, 11, 3),   # confirmed: Nov 3, 2026
        "biannual_months": None,                        # annual, not biannual
        "biannual_day": None,
        "open_threshold_days": 60,
        "final_call": "The Ambizione call opening in August 2026 (deadline November 2026) is "
                      "the final Ambizione call; a new career funding scheme will launch in 2028.",
        "grant_types":  ["Research Grant", "Fellowship"],
        "individual":   ["Early Career Researcher", "Postdoctoral Researcher"],
        "org_types":    ["University", "Research Institution"],
        "sectors":      ["Research & Innovation", "Science & Technology", "Health Sciences",
                         "Social Sciences & Humanities"],
        "desc": (
            "SNSF Ambizione grants support early-career researchers who wish to conduct, manage "
            "and lead an independent research project at a Swiss higher education institution. "
            "An Ambizione grant covers the grantee's salary and the project costs needed to "
            "carry out the project, for a maximum of four years. Applicants must hold a PhD, "
            "typically within four years of completion, and must have a connection to Switzerland "
            "(Swiss nationality, Swiss degree, or at least 12 months of research activity in "
            "Switzerland). Applications are submitted via mySNF, three months before the "
            "November deadline. Note: Ambizione is being discontinued; the November 2026 call "
            "is the final one, with a new career scheme launching in 2028."
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


def _strip_tags(html: str) -> str:
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    return re.sub(r'\s+', ' ', html).strip()


def _parse_ddmmyyyy(text: str) -> datetime.date | None:
    """Parse first DD.MM.YYYY date found in text."""
    m = re.search(r'\b(\d{2})\.(\d{2})\.(\d{4})\b', text)
    if m:
        day, month, year = int(m.group(1)), int(m.group(2)), int(m.group(3))
        try:
            return datetime.date(year, month, day)
        except ValueError:
            pass
    return None


def _find_submission_deadline(html: str, today: datetime.date) -> datetime.date | None:
    """
    Parse the submission deadline from a SNSF scheme page.
    The page contains 'Submission deadline:\n\nDD.MM.YYYY HH:MM ...' near the top.
    Returns the first future date found, or None.
    """
    text = _strip_tags(html)

    # Primary: "Submission deadline: DD.MM.YYYY" (Swiss format used throughout)
    # Find all DD.MM.YYYY dates in the whole page and return the first future one
    # near the "Submission deadline" label
    pat = r'[Ss]ubmission\s+deadline[^\.0-9]{0,30}(\d{2}\.\d{2}\.\d{4})'
    for m in re.finditer(pat, text, re.IGNORECASE | re.DOTALL):
        d = _parse_ddmmyyyy(m.group(1))
        if d and d >= today:
            return d

    # Fallback: scan all DD.MM.YYYY dates in the page
    for m in re.finditer(r'\b(\d{2})\.(\d{2})\.(\d{4})\b', text):
        try:
            d = datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            if d >= today:
                return d
        except ValueError:
            continue
    return None


def _check_opens_future(html: str, today: datetime.date) -> bool:
    """
    Return True if the page indicates the call has not yet opened
    (i.e., there's a future opening date).
    """
    text = _strip_tags(html)
    # Pattern: "opens on 3 August 2026" / "Call 2026 opens on X"
    months_re = (
        r'(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December)'
    )
    pat = r'opens\s+on\s+(\d+\s+' + months_re + r'\s+\d{4})'
    m = re.search(pat, text, re.IGNORECASE)
    if m:
        raw = re.sub(r'(\d+)(?:st|nd|rd|th)\b', r'\1', m.group(1))
        for fmt in ("%d %B %Y", "%d %b %Y"):
            try:
                d = datetime.datetime.strptime(raw.strip(), fmt).date()
                if d > today:
                    return True
            except ValueError:
                continue
    return False


def _next_biannual(
    months: tuple[int, int],
    day: int,
    today: datetime.date,
) -> datetime.date:
    """Return the next future deadline given two months per year and a fixed day."""
    for year in (today.year, today.year + 1):
        for month in sorted(months):
            try:
                d = datetime.date(year, month, day)
            except ValueError:
                d = datetime.date(year, month, 28)
            if d >= today:
                return d
    # Should never reach here
    return datetime.date(today.year + 1, min(months), day)


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(scheme: dict, deadline: datetime.date, status: str) -> dict:
    today = datetime.date.today()
    deadline_iso = deadline.isoformat()
    deadline_raw = str(deadline.day) + " " + deadline.strftime("%B %Y")

    # Append final-call note if applicable
    desc = scheme["desc"]
    if scheme.get("final_call"):
        desc = desc  # already embedded in desc above

    return {
        "grant_title":              scheme["title"],
        "funder_name":              FUNDER,
        "source_url":               scheme["url"],
        "application_portal_url":   scheme["portal"],
        "description":              desc,
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
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["CH"],
        "geographic_focus_countries": ["CH"],
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
        cur.execute(
            """UPDATE grants SET
                grant_title = %s, description = %s,
                application_deadline = %s, application_deadline_raw = %s,
                current_status = %s, crawl_date = %s, content_hash = %s
               WHERE id = %s""",
            (
                record["grant_title"], record["description"],
                record["application_deadline"], record["application_deadline_raw"],
                record["current_status"], record["crawl_date"], record["content_hash"],
                existing[0],
            ),
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
    parser = argparse.ArgumentParser(description="SNSF Switzerland connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip live page fetch; use fallback dates")
    args = parser.parse_args()

    today = datetime.date.today()
    records: list[dict] = []

    for scheme in SCHEMES:
        title = scheme["title"]
        print(f"  Fetching {title} …")

        deadline: datetime.date | None = None
        opens_future = False
        src = "fallback"

        if not args.skip_fetch:
            html = _fetch(scheme["url"])
            if html:
                deadline = _find_submission_deadline(html, today)
                opens_future = _check_opens_future(html, today)
                if deadline:
                    src = "live"

        # Resolve deadline
        if deadline and deadline >= today:
            final_deadline = deadline
        elif scheme["biannual_months"]:
            # Biannual scheme: compute next cycle
            final_deadline = _next_biannual(
                scheme["biannual_months"],
                scheme["biannual_day"],
                today,
            )
            src = "pattern"
        else:
            # Annual / single scheme: advance fallback by 1 year if past
            est = scheme["fallback_next"]
            if est < today:
                try:
                    est = est.replace(year=est.year + 1)
                except ValueError:
                    est = datetime.date(est.year + 1, est.month, 28)
            final_deadline = est
            src = "fallback"

        # Determine status
        days_until = (final_deadline - today).days
        if opens_future:
            status = "Forthcoming"   # explicitly not yet open
        elif days_until <= scheme["open_threshold_days"]:
            status = "Open"
        else:
            status = "Forthcoming"

        rec = _build_record(scheme, final_deadline, status)
        records.append(rec)
        print(f"    [{status:12s}] → {final_deadline}  ({src})")
        time.sleep(1)

    print(f"\n  Total: {len(records)} records")
    for r in records:
        print(f"  [{r['current_status']:12s}] {r['grant_title'][:65]}  → {r['application_deadline']}")

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
