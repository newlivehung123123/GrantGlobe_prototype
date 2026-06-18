#!/usr/bin/env python3
"""
ARC (Australian Research Council) connector.

Covers the National Competitive Grants Program (NCGP) major schemes:
  - Future Fellowships (FT): closes ~November each year, funding from July +1yr
  - Discovery Early Career Researcher Award (DECRA): closes ~March each year
  - Discovery Projects (DP): closes ~March each year
  - Linkage Projects (LP): closes ~March each year
  - Linkage Infrastructure, Equipment & Facilities (LIEF): closes ~April each year
  - Discovery Indigenous (DI): closes ~August each year

ARC grants follow predictable annual rounds. This connector fetches each
scheme's page to detect open deadlines; when no open round is found, it
generates a "Forthcoming" record with a pattern-estimated date.

Note: The NCGP was under a policy review in mid-2026, which may affect
exact timing of upcoming rounds. All records include a verification note.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/arc_australia.py [--dry-run]
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

FUNDER  = "Australian Research Council (ARC)"
DOMAIN  = "api_arc"
PORTAL  = "https://www.arc.gov.au/funding-research/apply-funding"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-AU,en;q=0.9",
}

_POLICY_NOTE = (
    " Note: the NCGP is currently undergoing a policy review — "
    "verify exact dates at arc.gov.au before applying."
)

# Month name pattern for date regex
_MONTHS = (
    r'(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
)
_DATE_PAT = (
    rf'(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\s+\d{{4}}'
    rf'|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})'
)

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------
# Each scheme defines:
#   url          - scheme page (some are server-rendered, some JS-rendered)
#   next_close   - estimated next application closing date (based on annual pattern)
#   status_kw    - regex keyword(s) to find the closing date on the page
#   grant_types  - GrantGlobe grant type tags
#   individual   - individual eligibility tags
#   sectors      - thematic sector tags
#   desc         - description text
# ---------------------------------------------------------------------------

SCHEMES = [
    {
        "title":       "ARC Future Fellowships",
        "code":        "FT",
        "url":         "https://www.arc.gov.au/funding-research/funding-schemes/discovery-program/future-fellowships",
        "next_close":  datetime.date(2026, 11, 5),   # typical: first week November
        "status_kw":   r'[Cc]losing?\s+date|[Cc]lose[sd]?\b|[Dd]eadline',
        "grant_types": ["Fellowship"],
        "individual":  ["Mid-career Researcher"],
        "sectors":     ["Research & Innovation", "Science & Technology"],
        "org_types":   ["University"],
        "desc": (
            "ARC Future Fellowships provide 4-year fellowships to outstanding mid-career "
            "researchers (typically with PhD 7–15 years prior) to undertake high-quality "
            "research in areas of national and international benefit. Up to 100 fellowships "
            "may be awarded each year. Fellows receive salary support plus up to AUD 60,000 "
            "per year in project funding. Applications submitted via the ARC Research "
            "Management System (RMS) through the applicant's university research office."
        ),
    },
    {
        "title":       "ARC Discovery Early Career Researcher Award (DECRA)",
        "code":        "DE",
        "url":         "https://www.arc.gov.au/funding-research/funding-schemes/discovery-program/discovery-early-career-researcher-award-decra",
        "next_close":  datetime.date(2027, 3, 15),   # typical: mid-March
        "status_kw":   r'[Cc]losing?\s+date|[Cc]lose[sd]?\b|[Dd]eadline',
        "grant_types": ["Fellowship", "Research Grant"],
        "individual":  ["Early Career Researcher"],
        "sectors":     ["Research & Innovation", "Science & Technology"],
        "org_types":   ["University"],
        "desc": (
            "ARC DECRA provides early career researchers with 3-year awards combining salary "
            "support and project funding (up to AUD 50,000 per year). Up to 200 awards made "
            "annually across all discipline areas. Applicants must hold a PhD typically "
            "awarded within the previous 5–6 years (with allowances for career interruptions). "
            "Applications are lodged through university research offices via the ARC RMS."
        ),
    },
    {
        "title":       "ARC Discovery Projects",
        "code":        "DP",
        "url":         "https://www.arc.gov.au/funding-research/funding-schemes/discovery-program/discovery-projects",
        "next_close":  datetime.date(2027, 3, 15),   # typical: mid-March (EOI ~December prior)
        "status_kw":   r'[Cc]losing?\s+date|[Cc]lose[sd]?\b|[Dd]eadline|[Ff]ull\s+[Aa]pplication',
        "grant_types": ["Research Grant"],
        "individual":  [],
        "sectors":     ["Research & Innovation", "Science & Technology"],
        "org_types":   ["University", "Research Institution"],
        "desc": (
            "ARC Discovery Projects fund excellent basic and applied research by individuals "
            "and teams across all disciplines. Projects typically run 3–5 years with funding "
            "AUD 50,000–500,000 per year. Applications follow a two-step process: Expression "
            "of Interest (EOI) around December, then full application around March. Submitted "
            "via university research offices through the ARC RMS."
        ),
    },
    {
        "title":       "ARC Linkage Projects",
        "code":        "LP",
        "url":         "https://www.arc.gov.au/funding-research/funding-schemes/linkage-program/linkage-projects",
        "next_close":  datetime.date(2027, 3, 18),   # typical: mid-to-late March
        "status_kw":   r'[Cc]losing?\s+date|[Cc]lose[sd]?\b|[Dd]eadline',
        "grant_types": ["Research Grant"],
        "individual":  [],
        "sectors":     ["Research & Innovation", "Technology & Innovation"],
        "org_types":   ["University", "Research Institution", "Industry"],
        "desc": (
            "ARC Linkage Projects promote research partnerships between higher education "
            "organisations and industry/community partners. Partner organisations must "
            "provide matching cash or in-kind contributions. Project funding AUD 50,000–"
            "300,000 per year for 2–5 years. Applications via the ARC RMS through a "
            "university research office; industry partners are named co-applicants."
        ),
    },
    {
        "title":       "ARC Linkage Infrastructure, Equipment and Facilities (LIEF)",
        "code":        "LE",
        "url":         "https://www.arc.gov.au/linkage-infrastructure-equipment-and-facilities-lief",
        "next_close":  datetime.date(2027, 4, 10),   # typical: early-to-mid April
        "status_kw":   r'[Cc]losing?\s+date|[Cc]lose[sd]?\b|[Dd]eadline',
        "grant_types": ["Research Grant", "Infrastructure Grant"],
        "individual":  [],
        "sectors":     ["Research & Innovation", "Science & Technology"],
        "org_types":   ["University", "Research Institution"],
        "desc": (
            "ARC LIEF grants fund shared research infrastructure, equipment and facilities "
            "across multiple institutions. Awards cover a wide range of research equipment "
            "and infrastructure needs. Universities apply collaboratively, with the lead "
            "institution coordinating the submission via the ARC RMS."
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


def _fetch(url: str, timeout: int = 20) -> str | None:
    """Fetch a URL; return None on any error."""
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception:
        return None


def _strip_tags(html: str) -> str:
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    return re.sub(r'\s+', ' ', html).strip()


def _parse_date_str(text: str) -> datetime.date | None:
    text = re.sub(r'(\d+)(?:st|nd|rd|th)\b', r'\1', text.strip())
    text = re.sub(r'\s+', ' ', text)
    for fmt in (
        "%B %d, %Y", "%B %d %Y",
        "%d %B %Y",  "%d %b %Y",
        "%b %d, %Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _find_closing_date(html: str, keyword_re: str, today: datetime.date) -> datetime.date | None:
    """
    Look for a future closing date near a keyword in page text.
    Returns the first upcoming date found, or None.
    """
    text = _strip_tags(html)
    pattern = keyword_re + r'.{0,200}?(' + _DATE_PAT + r')'
    for m in re.finditer(pattern, text, re.IGNORECASE | re.DOTALL):
        d = _parse_date_str(m.group(1))
        if d and d >= today:
            return d
    # Also try the inverse: date then keyword
    pattern2 = r'(' + _DATE_PAT + r').{0,100}?' + keyword_re
    for m in re.finditer(pattern2, text, re.IGNORECASE | re.DOTALL):
        d = _parse_date_str(m.group(1))
        if d and d >= today:
            return d
    return None


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(
    scheme: dict,
    deadline: datetime.date | None,
    status: str,
) -> dict:
    today = datetime.date.today()
    title = scheme["title"]
    url   = scheme["url"]
    desc  = scheme["desc"] + _POLICY_NOTE

    deadline_iso = deadline.isoformat() if deadline else None
    deadline_raw = (
        str(deadline.day) + " " + deadline.strftime("%B %Y")
        if deadline else None
    )
    return {
        "grant_title":              title,
        "funder_name":              FUNDER,
        "source_url":               url,
        "application_portal_url":   PORTAL,
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
        "applicant_base_regions":   ["Asia Pacific"],
        "geographic_focus_regions": ["Asia Pacific"],
        "applicant_base_countries": ["AU"],
        "geographic_focus_countries": ["AU"],
        "organisation_types":       scheme["org_types"],
        "individual_eligibility":   scheme["individual"],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(url, title, deadline_iso or ""),
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
    parser = argparse.ArgumentParser(description="ARC Australia connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip page fetching; use pattern dates only")
    args = parser.parse_args()

    today = datetime.date.today()
    records: list[dict] = []

    for scheme in SCHEMES:
        print(f"  Checking {scheme['title']} …")
        open_deadline: datetime.date | None = None

        # Try to detect an open deadline from the scheme page
        if not args.skip_fetch:
            html = _fetch(scheme["url"])
            if html and len(html) > 500:   # non-empty, non-shell response
                open_deadline = _find_closing_date(html, scheme["status_kw"], today)
                if open_deadline:
                    print(f"    Found open deadline on page: {open_deadline}")

        if open_deadline:
            # Live open round detected
            rec = _build_record(scheme, open_deadline, "Open")
            print(f"    → Open  {open_deadline}")
        else:
            # No open round — use pattern estimate as Forthcoming
            est = scheme["next_close"]
            # If the static estimate has also passed, advance by one year
            if est < today:
                try:
                    est = est.replace(year=est.year + 1)
                except ValueError:
                    est = datetime.date(est.year + 1, est.month, 28)
            rec = _build_record(scheme, est, "Forthcoming")
            print(f"    → Forthcoming  {est}  (estimated)")

        records.append(rec)
        time.sleep(0.5)

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
