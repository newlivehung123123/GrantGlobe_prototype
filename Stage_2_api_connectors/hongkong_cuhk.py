#!/usr/bin/env python3
"""
Chinese University of Hong Kong (CUHK) — Research Institute for the
Humanities Postdoctoral Fellowship Program connector.

Distinct from the Research Grants Council schemes covered in
hongkong_rgc.py, this is CUHK's own institutional postdoctoral fellowship,
run by its Research Institute for the Humanities (RIH) to attract
early-career humanities scholars worldwide. The fellowship is awarded
annually, with applications accepted online through CUHK's central Human
Resources careers portal.

Eligibility requires the PhD to be awarded within a defined window before
the fellowship start, with the applicant no more than three years beyond
the doctorate at the start of the fellowship term. The appointment is
non-renewable and cannot be held concurrently with other fellowships or
academic positions.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://rih.cuhk.edu.hk/news-and-events/pdf202628/
Portal: https://rih.cuhk.edu.hk/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/hongkong_cuhk.py [--dry-run]
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

FUNDER = "Chinese University of Hong Kong (CUHK) — Research Institute for the Humanities"
DOMAIN = "api_hongkong_cuhk_rih"
BASE   = "https://rih.cuhk.edu.hk/news-and-events/pdf202628/"
PORTAL = "https://rih.cuhk.edu.hk/"

SCHEMES: list[dict] = [
    {
        "title":   "CUHK Research Institute for the Humanities Postdoctoral Fellowship",
        "url":     BASE,
        "portal":  PORTAL,
        # 2026-2028 intake: applications closed 31 January 2026 (already
        # closed at authoring time). Advances annually to the next intake.
        "deadline": datetime.date(2026, 1, 31),
        "open_threshold_days": 65,        # applications open ~1 December each year
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "HKD",
        "sectors": [
            "Humanities", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["HK"],
        "desc": (
            "The Research Institute for the Humanities (RIH) Postdoctoral "
            "Fellowship Program at the Chinese University of Hong Kong "
            "(CUHK) attracts early-career humanities scholars from "
            "worldwide to conduct research at CUHK. Applicants must have "
            "been awarded a PhD by the fellowship's intake cut-off date "
            "(e.g. for the 2026-2028 intake, by 31 July 2026), and must "
            "be no more than three years beyond receipt of the doctoral "
            "degree at the start of the fellowship. Salary is highly "
            "competitive, commensurate with qualifications and "
            "experience, and fellows are eligible for research support "
            "for conference attendance and other scholarly activities. "
            "The appointment is non-renewable and cannot be held "
            "concurrently with other fellowships or academic positions. "
            "Applications are accepted online through CUHK's central "
            "Human Resources careers portal. For the 2026-2028 intake, "
            "the application period opened 1 December 2025 and closed "
            "31 January 2026; subsequent intakes follow a similar annual "
            "schedule."
        ),
    },
    {
        # ── 2. CUHK Vice-Chancellor's PhD Scholarship Scheme ──────────────────
        "title":    "CUHK Vice-Chancellor's PhD Scholarship Scheme",
        "url":      "https://www.gs.cuhk.edu.hk/admissions/scholarships-fees/scholarships",
        "portal":   "https://www.gs.cuhk.edu.hk/admissions",
        # Main round full-application deadline: 1 December each year.
        "deadline": datetime.date(2025, 12, 1),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["PhD Scholarship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": 229200,
        "amount_max": 309200,
        "currency": "HKD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["HK"],
        "desc": (
            "The CUHK Vice-Chancellor's PhD Scholarship Scheme offers "
            "the Chinese University of Hong Kong's flagship scholarship "
            "to outstanding new full-time PhD students worldwide with a "
            "clear record of academic and/or research achievement, high "
            "intellectual curiosity and creativity, and potential for "
            "academic or professional leadership. The scholarship "
            "comprises a total award of HK$80,000 (HK$40,000 in year one "
            "and HK$20,000 in each of years two and three, subject to "
            "satisfactory progress), an annual studentship of HK$229,200 "
            "within the normative study period, and a Conference and "
            "Research-related Travel Allowance totalling HK$30,000 over "
            "the scholarship period. Candidates applying to CUHK's "
            "full-time PhD programmes through the Online Application "
            "System by the standard application deadline are "
            "automatically considered; no separate scholarship "
            "application is required. The submission deadline for a "
            "full application was 1 December 2025, 11:59pm (Hong Kong "
            "time); subsequent intakes follow a similar annual schedule."
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
        cur.execute(
            """UPDATE grants SET
                grant_title = %s, description = %s,
                application_deadline = %s, application_deadline_raw = %s,
                grant_opening_date = %s, current_status = %s,
                crawl_date = %s, content_hash = %s,
                domain = %s
               WHERE id = %s""",
            (
                db_rec["grant_title"], db_rec["description"],
                db_rec["application_deadline"], db_rec["application_deadline_raw"],
                db_rec["grant_opening_date"], db_rec["current_status"],
                db_rec["crawl_date"], db_rec["content_hash"],
                db_rec["domain"],
                existing[0],
            ),
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
    parser = argparse.ArgumentParser(description="CUHK RIH Postdoctoral Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  CUHK RIH Postdoctoral Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  CUHK RIH: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
