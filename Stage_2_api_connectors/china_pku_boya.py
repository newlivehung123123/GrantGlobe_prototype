#!/usr/bin/env python3
"""
Peking University — Boya Postdoctoral Fellowship connector.

The Boya Postdoctoral Fellowship, initiated in 2016, is Peking University's
flagship postdoctoral recruitment programme, open to outstanding
researchers of all nationalities under the age of 35 who have obtained
their PhD within the past three years (or anticipate doing so by the
relevant round's cut-off). It spans natural sciences, social sciences,
humanities, economics and business, information technology and
engineering, and interdisciplinary studies. Application documents (the
application form, supervisor endorsement letter, and recommendation
letters) are explicitly accepted in either Chinese or English.

The programme runs two recruitment rounds per year: Round One (calls for
applications 1 January – 28 February) and Round Two (calls for
applications 1 September – 10 October). For the 2026 academic year, up to
380 fellowships are available in total (200 in Round One, 180 in Round
Two). This connector models each round as a separate scheme using the
annual cyclical-advance pattern.

Source: https://postdocs.pku.edu.cn/tzgg/f6f8ed4941c94e92ae8528edb7facc66.htm
Portal: https://postdocs.pku.edu.cn/Home/index.htm

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/china_pku_boya.py [--dry-run]
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

FUNDER = "Peking University — Boya Postdoctoral Fellowship"
DOMAIN = "api_china_pku_boya"
BASE   = "https://postdocs.pku.edu.cn/tzgg/f6f8ed4941c94e92ae8528edb7facc66.htm"
PORTAL = "https://postdocs.pku.edu.cn/Home/index.htm"

DESC = (
    "The Boya Postdoctoral Fellowship, initiated in 2016, aims to draw "
    "prospective young talent worldwide to conduct postdoctoral research "
    "at Peking University across natural sciences, social sciences, "
    "humanities, economics and business, information technology and "
    "engineering, and interdisciplinary studies. The fellowship is open "
    "to outstanding researchers of all nationalities who are under the "
    "age of 35 and have obtained their PhD within the past three years "
    "(or anticipate doing so by the relevant round's cut-off date). Each "
    "fellowship runs for 24 months and provides an annual pre-tax salary "
    "of 200,000 RMB, social insurance, housing allowances, and other "
    "benefits, plus a 60,000 RMB subsidy for fellows without access to "
    "postdoctoral housing; postdoctoral supervisors may additionally "
    "offer a discretionary top-up of 30,000, 60,000, or 90,000 RMB per "
    "year based on the applicant's academic potential. Applicants must "
    "secure a Peking University faculty member as postdoctoral "
    "supervisor and obtain their written endorsement, plus two "
    "recommendation letters (one from the applicant's doctoral advisor). "
    "All application documents may be prepared in either Chinese or "
    "English. For the 2026 academic year, up to 380 fellowships are "
    "available across two rounds: Round One (up to 200 fellowships, "
    "applications 1 January–28 February 2026) and Round Two (up to 180 "
    "fellowships, applications 1 September–10 October 2026). Completed "
    "applications are compiled into a single PDF and emailed to the "
    "coordinator of the relevant school, department, institute, or "
    "centre at Peking University; coordinator contact details are "
    "published alongside each round's call for applications."
)

SCHEMES: list[dict] = [
    {
        "title":    "PKU Boya Postdoctoral Fellowship — Round One",
        "url":      BASE,
        "portal":   PORTAL,
        # Round One: applications close 28 February each year.
        "deadline": datetime.date(2026, 2, 28),
        "open_threshold_days": 58,        # call opens 1 January each year
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  [],
        "amount_min": 200000,
        "amount_max": 350000,
        "currency":   "CNY",
        "sectors": [
            "Science & Technology", "Engineering", "Humanities",
            "Social Sciences", "Economics & Business",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["CN"],
        "desc": DESC,
    },
    {
        "title":    "PKU Boya Postdoctoral Fellowship — Round Two",
        "url":      BASE,
        "portal":   PORTAL,
        # Round Two: applications close 10 October each year.
        "deadline": datetime.date(2026, 10, 10),
        "open_threshold_days": 40,        # call opens 1 September each year
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  [],
        "amount_min": 200000,
        "amount_max": 350000,
        "currency":   "CNY",
        "sectors": [
            "Science & Technology", "Engineering", "Humanities",
            "Social Sciences", "Economics & Business",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["CN"],
        "desc": DESC,
    },
    {
        # ── 3. Peking-Princeton Postdoctoral Program (PPPP) ───────────────────
        "title":    "Peking-Princeton Postdoctoral Program (PPPP)",
        "url":      "https://postdocs.pku.edu.cn/tzgg/f74d3156b9be48dca9126aafbd2ea1e9.htm",
        "portal":   "https://apply.interfolio.com/181473",
        # Annual application deadline: 24 March (already closed at
        # authoring time for the 2026-28 cohort).
        "deadline": datetime.date(2026, 3, 24),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "CNY",
        "sectors": [
            "Chinese Studies", "Area Studies", "Social Sciences",
            "Humanities", "International Relations",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CN"],
        "desc": (
            "The Peking-Princeton Postdoctoral Program (PPPP), jointly "
            "run by Peking University and Princeton University, trains "
            "highly qualified early-career postdoctoral researchers in "
            "studies of contemporary China. Each two-year fellowship "
            "spans 12 consecutive months at Peking University followed "
            "by 12 consecutive months at Princeton University (with a "
            "visiting appointment retained at Peking University), with "
            "renewal after the first year contingent on performance and "
            "funding. The position is open to any discipline so long as "
            "the fellow's research focuses on contemporary China, and is "
            "open to researchers of all nationalities with no more than "
            "one year of post-PhD experience at the start of the "
            "appointment; applicants holding tenure or tenure-track "
            "positions are not eligible. Benefits at Peking University "
            "are provided through the Boya Postdoctoral Fellowship "
            "Program; benefits at Princeton include travel funding and "
            "access to the Paul and Marcia Wythes Center on Contemporary "
            "China. Candidates require endorsement from a supervisor at "
            "each university. The annual application deadline is 24 "
            "March, 11:59pm EST; applications are submitted via "
            "https://apply.interfolio.com/."
        ),
    },
    {
        # ── 4. PKU-IIASA International Postdoctoral Fellowship Program ────────
        "title":    "PKU-IIASA International Postdoctoral Fellowship Program",
        "url":      "https://postdocs.pku.edu.cn/tzgg/add6713771164dde92df13dc03645b08.htm",
        "portal":   "https://iiasa.ac.at/opportunities/pku-iiasa-postdoctoral-program",
        # Annual application deadline: 10 April.
        "deadline": datetime.date(2026, 4, 10),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "CNY",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Environmental Science", "Economics & Business",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CN"],
        "desc": (
            "The PKU-IIASA International Postdoctoral Fellowship "
            "Program, jointly run by Peking University and the "
            "International Institute for Applied Systems Analysis "
            "(IIASA, Austria), offers up to five two-year postdoctoral "
            "fellowships per year to early-career researchers tackling "
            "advanced methodological, technological, economic, and "
            "environmental challenges. Fellows ideally spend the first "
            "12 months at Peking University and the subsequent 12 "
            "months at IIASA, with appointments typically starting "
            "between September and December. Required application "
            "materials include the programme's application form, two "
            "recommendation letters (one from the applicant's doctoral "
            "supervisor), and endorsement letters from prospective "
            "supervisors at both PKU and IIASA. The annual application "
            "deadline is 10 April, with selection results notified in "
            "early May."
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


def _advance_deadline(
    est: datetime.date,
    cycle_years: int,
    today: datetime.date,
) -> datetime.date:
    while est < today:
        try:
            est = est.replace(year=est.year + cycle_years)
        except ValueError:
            est = datetime.date(est.year + cycle_years, est.month, 28)
    return est


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(scheme: dict, today: datetime.date) -> dict:
    deadline = _advance_deadline(scheme["deadline"], scheme["cycle_years"], today)
    days_until = (deadline - today).days
    thr = scheme["open_threshold_days"]

    if days_until < 0:
        status = "Closed"
    elif days_until <= thr:
        status = "Open"
    else:
        status = "Forthcoming"

    opening = deadline - datetime.timedelta(days=thr)
    deadline_iso = deadline.isoformat()

    return {
        "grant_title":               scheme["title"],
        "funder_name":               FUNDER,
        "source_url":                scheme["url"],
        "application_portal_url":    scheme["portal"],
        "description":               scheme["desc"],
        "application_deadline":      deadline_iso,
        "application_deadline_raw":  scheme.get(
            "deadline_raw", f"{deadline.day} {deadline.strftime('%B %Y')}"
        ),
        "grant_opening_date":        opening.isoformat(),
        "current_status":            status,
        "source_language":           "en",
        "funding_amount_min":        scheme["amount_min"],
        "funding_amount_max":        scheme["amount_max"],
        "currency":                  scheme["currency"],
        "thematic_sectors":          scheme["sectors"],
        "grant_types":               scheme["grant_types"],
        "applicant_base_regions":    [],
        "geographic_focus_regions":  scheme["focus_regions"],
        "applicant_base_countries":  scheme["applicant_countries"],
        "geographic_focus_countries": scheme["focus_countries"],
        "organisation_types":        scheme["org_types"],
        "individual_eligibility":    scheme["individual"],
        "domain":                    DOMAIN,
        "review_status":             "approved",
        "requires_review":           False,
        "crawl_date":                today.isoformat(),
        "content_hash":              _content_hash(
                                         scheme["url"], scheme["title"], deadline_iso
                                     ),
        "_days_until": days_until,
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    db_rec = {k: v for k, v in record.items() if not k.startswith("_")}
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s", (db_rec["source_url"],))
    existing = cur.fetchone()

    if existing:

        _upd_cols = [c for c in db_rec if c != "source_url"]
        _set_clause = ", ".join(f"{c} = %({c})s" for c in _upd_cols)
        cur.execute(
            f"UPDATE grants SET {_set_clause} WHERE id = %(id)s",
            {**db_rec, "id": existing[0]},
        )
        return "updated"

    cols = list(db_rec.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) "
        f"VALUES ({', '.join(['%s'] * len(cols))})",
        [db_rec[c] for c in cols],
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="PKU Boya Postdoctoral Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  PKU Boya Postdoctoral Fellowship — {len(records)} scheme(s)  (today: {today})")
    print(f"{'─'*70}")
    for rec in records:
        print(
            f"  [{rec['current_status']:<13}] {rec['grant_title'][:52]} "
            f"→ {rec['application_deadline']}  ({rec['_days_until']}d)"
        )

    if args.dry_run:
        print("\n[DRY RUN] Full records:")
        for rec in records:
            display = {k: v for k, v in rec.items() if not k.startswith("_")}
            print(json.dumps(display, indent=2, default=str))
        return

    conn = _connect()
    inserted = updated = err = 0
    for record in records:
        try:
            result = _upsert(conn, record)
            conn.commit()
            print(f"  {result:9}  {record['grant_title']}")
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            conn.rollback()
            print(f"  ERROR [{record['grant_title'][:50]}]: {e}", file=sys.stderr)
            err += 1
    conn.close()
    print(f"\n  PKU Boya: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
