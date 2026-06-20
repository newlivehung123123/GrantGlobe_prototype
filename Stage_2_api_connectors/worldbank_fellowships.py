#!/usr/bin/env python3
"""
World Bank Group connector — research and graduate scholarship
programmes.

The World Bank Group publishes many "calls for proposals," but most are
procurement tenders or development-implementation contracts for
organisations, not grants an individual researcher applies to. This
connector instead covers two genuine researcher/student-facing
programmes (the Robert S. McNamara Fellowships Program was checked and
confirmed discontinued as of a July 2024 World Bank brief, and is not
included; the Young Professionals Program, Junior Professional
Associates, and MNA Fellows Program are standard early-career employment
tracks rather than research grants, and are likewise excluded):

1. World Bank Group Africa Fellowship Program — for PhD students
   (final year) and recent PhD graduates who are Sub-Saharan African
   nationals, providing six months of hands-on development-research
   experience at World Bank offices.

2. Joint Japan/World Bank Graduate Scholarship Program (JJ/WBGSP) — for
   professionals from a list of eligible developing countries to pursue
   master's degrees in development-related fields at leading
   universities worldwide, funded by the Government of Japan and
   administered by the World Bank.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.worldbank.org/en/programs/scholarships
Portal: https://www.worldbank.org/en/programs/scholarships

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/worldbank_fellowships.py [--dry-run]
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

FUNDER = "World Bank Group"
DOMAIN = "api_worldbank_fellowships"

SCHEMES: list[dict] = [
    {
        "title":   "World Bank Group Africa Fellowship Program",
        "url":     "https://wbgfellowship.worldbank.org/",
        "portal":  "https://wbgfellowship.worldbank.org/",
        # 2026 cohort: application deadline 25 August 2025 (already
        # closed at authoring time).
        "deadline": datetime.date(2025, 8, 25),
        "open_threshold_days": 56,        # application period opens ~1 July
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["PhD Student", "Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Economics", "Development Studies", "Public Policy",
            "Research & Innovation",
        ],
        "applicant_countries": [
            "NG", "KE", "GH", "ZA", "ET",
            "TZ", "UG", "SN", "RW", "ZM",
        ],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "The World Bank Group Africa Fellowship Program offers "
            "Ph.D. students (in their final year) and recent Ph.D. "
            "graduates who are Sub-Saharan African nationals a six-month "
            "fellowship, running January to June, with hands-on "
            "experience in development work, research, economic policy, "
            "technical assistance, and lending operations. Fellows "
            "spend at least six months at World Bank offices in "
            "Washington, D.C. or in a Sub-Saharan African country. "
            "Eligibility requires applicants to be under 32 years old by "
            "the deadline, have excellent English, and demonstrate "
            "strong quantitative and analytical capabilities. Fellows "
            "receive consultant fees, economy-class air travel, and "
            "workers' compensation insurance. The application period "
            "for the 2026 cohort ran 1 July to 25 August 2025 (in 2025, "
            "over 3,000 applications were submitted for 26 fellowship "
            "places); subsequent cohorts follow a similar annual "
            "schedule. Full details are published at "
            "https://wbgfellowship.worldbank.org/."
        ),
    },
    {
        "title":   "Joint Japan/World Bank Graduate Scholarship Program (JJ/WBGSP)",
        "url":     "https://www.worldbank.org/en/programs/scholarships",
        "portal":  "https://www.worldbank.org/en/programs/scholarships",
        # 2026 cycle: Application Window for developing-country nationals
        # runs 30 March - 29 May 2026 (already closed at authoring time).
        "deadline": datetime.date(2026, 5, 29),
        "open_threshold_days": 60,        # window opens ~30 March
        "cycle_years": 1,
        "grant_types": ["Graduate Scholarship"],
        "individual": ["Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Development Studies", "Economics", "Public Policy",
            "Research & Innovation",
        ],
        "applicant_countries": [
            "AF", "BD", "KE", "NG", "PK",
            "PH", "IN", "GH", "TZ", "UG",
            "NP", "ET", "MZ", "KH", "MM",
        ],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "The Joint Japan/World Bank Graduate Scholarship Program "
            "(JJ/WBGSP) is a highly competitive, fully funded scholarship "
            "supporting professionals from a defined list of developing "
            "countries to pursue master's degrees in development-related "
            "fields at leading universities worldwide. Funded by the "
            "Government of Japan and administered by the World Bank, "
            "the programme has enabled more than 7,000 mid-career "
            "professionals from over 160 developing countries to "
            "complete graduate degrees since 1987. The scholarship "
            "covers tuition, a monthly living stipend, round-trip "
            "airfare, health insurance, and a travel allowance. The "
            "2026 cycle's Application Window for developing-country "
            "nationals ran 30 March to 29 May 2026 (a separate window "
            "for Japanese nationals ran 16 February to 17 April 2026); "
            "subsequent cycles follow a similar annual schedule. Full "
            "eligible-country list and application details are "
            "published at "
            "https://www.worldbank.org/en/programs/scholarships."
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
    cur.execute(
        "SELECT id FROM grants WHERE source_url = %s AND grant_title = %s",
        (db_rec["source_url"], db_rec["grant_title"]),
    )
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
    parser = argparse.ArgumentParser(description="World Bank fellowships connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  World Bank Group — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  World Bank Group: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
