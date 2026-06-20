#!/usr/bin/env python3
"""
Commonwealth Scholarship Commission (CSC) connector.

The CSC administers UK Government-funded scholarships and fellowships for
citizens of Commonwealth countries, disbursing approximately 800+ awards
annually across postgraduate study, research, and professional development
at UK universities.

Programs covered:
  - Commonwealth PhD Scholarships (least developed/fragile Commonwealth states)
  - Commonwealth Shared Scholarships (low/middle-income Commonwealth countries)
  - Commonwealth Distance Learning Scholarships (developing Commonwealth)
  - Commonwealth Professional Fellowships (mid-career professionals)

Annual cycles (all applications through CSC Central):
  - PhD Scholarships:          LOI/application ~October each year
  - Shared Scholarships:       application ~December each year
  - Distance Learning:         application ~March each year
  - Professional Fellowships:  application ~October/November each year

The CSC website (cscuk.fcdo.gov.uk) is JS-rendered and not directly crawlable.
This connector uses a curated static list updated from public sources.
All 2026/27 rounds have closed; records are "Forthcoming" for the 2027 cycle.
Verify exact dates at cscuk.fcdo.gov.uk before applying.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/csc_uk.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys

import psycopg2

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FUNDER  = "Commonwealth Scholarship Commission (CSC)"
DOMAIN  = "api_csc"
BASE    = "https://cscuk.fcdo.gov.uk"
PORTAL  = "https://csccentral.cscuk.fcdo.gov.uk/"

_VERIFY_NOTE = (
    " Verify exact opening and closing dates at cscuk.fcdo.gov.uk "
    "before applying — the CSC publishes updated timetables each cycle."
)

# ---------------------------------------------------------------------------
# Program definitions
# ---------------------------------------------------------------------------

PROGRAMS: list[dict] = [

    # ── PhD Scholarships ──────────────────────────────────────────────────────
    {
        "title":    "Commonwealth PhD Scholarships",
        "url":      f"{BASE}/scholarships/commonwealth-phd-scholarships-for-least-developed-countries-and-fragile-states/",
        "deadline": datetime.date(2026, 10, 14),   # typical: mid-October; 2026-27 was Oct 14, 2025
        "status":   "Forthcoming",
        "grant_types":  ["Scholarship", "Fellowship"],
        "individual":   ["Graduate Researcher", "Doctoral Researcher"],
        "org_types":    ["University"],
        "sectors":      ["Research & Innovation", "Education & Training", "Science & Technology"],
        "countries":    [],   # eligible from least-developed & fragile Commonwealth states
        "regions":      ["Sub-Saharan Africa", "South Asia", "Asia Pacific",
                         "Caribbean", "Pacific Islands", "East Africa & Horn"],
        "focus_countries": ["GB"],
        "desc": (
            "Commonwealth PhD Scholarships enable citizens of least-developed countries and "
            "fragile states within the Commonwealth to undertake full-time doctoral study at "
            "a UK university. Scholarships are fully funded by the UK Foreign, Commonwealth & "
            "Development Office (FCDO) and cover tuition fees, living allowance, return airfare, "
            "and ancillary expenses for up to 3 years. Applicants must hold at least an upper "
            "second-class (2:1) undergraduate degree and must apply through their national "
            "nominating agency (NNA). Applications are submitted via CSC Central, typically "
            "opening in August and closing in mid-October each year. Study commences the "
            "following September/October."
        ),
    },

    # ── Shared Scholarships ───────────────────────────────────────────────────
    {
        "title":    "Commonwealth Shared Scholarships",
        "url":      f"{BASE}/scholarships/commonwealth-shared-scholarships/",
        "deadline": datetime.date(2026, 12, 9),    # pattern: early December; 2026-27 was Dec 9, 2025
        "status":   "Forthcoming",
        "grant_types":  ["Scholarship"],
        "individual":   ["Masters Student", "Graduate Researcher"],
        "org_types":    ["University"],
        "sectors":      ["Education & Training", "Research & Innovation", "Development"],
        "countries":    [],   # low/middle-income Commonwealth countries
        "regions":      ["Sub-Saharan Africa", "South Asia", "Asia Pacific",
                         "Caribbean", "Pacific Islands"],
        "focus_countries": ["GB"],
        "desc": (
            "Commonwealth Shared Scholarships enable citizens of low and middle-income "
            "Commonwealth countries to pursue a one-year taught Masters degree at a UK "
            "university. Scholarships are jointly funded by the UK FCDO and participating "
            "UK universities. Awards cover full tuition fees, living allowance, return "
            "airfare, and study travel. Eligible fields are those that contribute to "
            "development in the candidate's home country. Applicants must not have studied "
            "or worked in a high-income country for more than 3 months in the last 5 years. "
            "Applications are submitted via CSC Central; university bids open earlier, "
            "with candidate applications typically closing in early December."
        ),
    },

    # ── Distance Learning Scholarships ────────────────────────────────────────
    {
        "title":    "Commonwealth Distance Learning Scholarships",
        "url":      f"{BASE}/scholarships/commonwealth-distance-learning-scholarships-candidates/",
        "deadline": datetime.date(2027, 3, 31),    # pattern: March 31; 2026-27 was Mar 31, 2026
        "status":   "Forthcoming",
        "grant_types":  ["Scholarship"],
        "individual":   ["Masters Student"],
        "org_types":    ["University"],
        "sectors":      ["Education & Training", "Research & Innovation", "Development"],
        "countries":    [],   # developing Commonwealth countries
        "regions":      ["Sub-Saharan Africa", "South Asia", "Asia Pacific",
                         "Caribbean", "Pacific Islands"],
        "focus_countries": ["GB"],
        "desc": (
            "Commonwealth Distance Learning Scholarships enable citizens of developing "
            "Commonwealth countries to study for a part-time Masters degree via distance "
            "learning while remaining in their home country. Scholarships are fully funded "
            "by the UK FCDO and cover course fees, study materials, and a technology "
            "allowance. Programmes are delivered by UK universities selected through a "
            "competitive bidding process. Candidates do not need to relocate to the UK. "
            "Applications open in February and typically close on 31 March each year "
            "via CSC Central."
        ),
    },

    # ── Professional Fellowships ──────────────────────────────────────────────
    {
        "title":    "Commonwealth Professional Fellowships",
        "url":      f"{BASE}/scholarships/commonwealth-professional-fellowships/",
        "deadline": datetime.date(2026, 11, 1),    # pattern: October/November; 2026 closed
        "status":   "Forthcoming",
        "grant_types":  ["Fellowship"],
        "individual":   ["Mid-career Professional", "Early Career Professional"],
        "org_types":    ["University", "Research Institution", "NGO", "Government"],
        "sectors":      ["Education & Training", "Development", "Health Sciences",
                         "Agriculture & Food", "Research & Innovation"],
        "countries":    [],   # developing Commonwealth countries
        "regions":      ["Sub-Saharan Africa", "South Asia", "Asia Pacific",
                         "Caribbean", "Pacific Islands"],
        "focus_countries": ["GB"],
        "desc": (
            "Commonwealth Professional Fellowships support mid-career professionals from "
            "developing Commonwealth countries to spend 6 weeks to 6 months at a UK "
            "host organisation, developing their skills and knowledge in areas relevant "
            "to their home country's development. Fellows receive a monthly stipend, "
            "return airfare, and relevant allowances. Open to professionals working in "
            "the public, private, NGO, or academic sector with at least 3 years' "
            "professional experience. Applications are submitted via CSC Central; "
            "candidates must apply through their national nominating agency. "
            "Typical application window: August to October/November each year."
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


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _build_record(prog: dict) -> dict:
    today = datetime.date.today()
    deadline = prog["deadline"]

    # If pattern estimate has already passed, advance by one year
    if deadline < today:
        try:
            deadline = deadline.replace(year=deadline.year + 1)
        except ValueError:
            deadline = datetime.date(deadline.year + 1, deadline.month, 28)

    deadline_iso = deadline.isoformat()
    deadline_raw = str(deadline.day) + " " + deadline.strftime("%B %Y")

    return {
        "grant_title":              prog["title"],
        "funder_name":              FUNDER,
        "source_url":               prog["url"],
        "application_portal_url":   PORTAL,
        "description":              prog["desc"] + _VERIFY_NOTE,
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       None,
        "current_status":           prog["status"],
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         prog["sectors"],
        "grant_types":              prog["grant_types"],
        "applicant_base_regions":   prog["regions"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": prog["countries"],
        "geographic_focus_countries": prog["focus_countries"],
        "organisation_types":       prog["org_types"],
        "individual_eligibility":   prog["individual"],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(prog["url"], prog["title"], deadline_iso),
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
    parser = argparse.ArgumentParser(description="Commonwealth Scholarship Commission connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(p) for p in PROGRAMS]

    print(f"  Total: {len(records)} records")
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
