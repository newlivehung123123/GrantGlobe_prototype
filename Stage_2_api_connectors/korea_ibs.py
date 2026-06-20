#!/usr/bin/env python3
"""
Institute for Basic Science (IBS), Korea connector.

IBS is Korea's national basic-science research institute, operating 30
research centres spanning mathematics, physics, chemistry, life sciences,
earth science, and interdisciplinary fields. This connector covers its
two early-career independent-research programmes, run as a single joint
annual call:

1. Young Scientist Fellowship (YSF) — for researchers within 7 years of
   PhD (or under 40), providing 3 years of independent research support
   (extendable by 2 years).

2. Junior Chief Investigator (Junior CI) — launched in 2024 for
   early-career researchers who have surpassed the YSF level, providing
   5 years of independent research support with greater research
   autonomy.

Both programmes are genuinely international: eligibility is based solely
on PhD timing (or, for Junior CI, ability to work full-time at an IBS
Research Center), with no nationality restriction stated, and candidates
residing abroad may be evaluated via video conference rather than
in-person interview.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.ibs.re.kr/eng/sub04_04_04.do
Portal: https://www.ibs.re.kr/ysf/apply (YSF) / https://www.ibs.re.kr/juniorci/apply (Junior CI)

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/korea_ibs.py [--dry-run]
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

FUNDER = "Institute for Basic Science (IBS), Korea"
DOMAIN = "api_korea_ibs"
BASE   = "https://www.ibs.re.kr/eng/sub04_04_04.do"

SCHEMES: list[dict] = [
    {
        "title":   "IBS Young Scientist Fellowship (YSF)",
        "url":     BASE,
        "portal":  "https://www.ibs.re.kr/prog/ysf_apply/eng/sub04_04_06/info.do",
        # Letter of intent submission deadline: 5 December each year
        # (already closed for the 2026 cycle at authoring time).
        "deadline": datetime.date(2025, 12, 5),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Postdoctoral Researcher", "Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "KRW",
        "sectors": [
            "Mathematics", "Physics", "Chemistry", "Life Sciences",
            "Earth Sciences", "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["KR"],
        "desc": (
            "The IBS Young Scientist Fellowship (YSF) was launched in "
            "2016 to foster the next generation of basic science "
            "leaders, offering young scientists the opportunity to "
            "conduct independent research using IBS's state-of-the-art "
            "research infrastructure across its 30 Research Centers, "
            "spanning mathematics, physics, chemistry, life sciences, "
            "earth science, and interdisciplinary fields. Eligible "
            "applicants are within seven years of obtaining a PhD "
            "(conferred no earlier than the relevant cut-off year) or "
            "under the age of 40 with a PhD already conferred; there is "
            "no nationality restriction. YSF appointments run three "
            "years, with a possible two-year extension subject to "
            "performance review, and provide an annual fund of KRW "
            "180-300 million (including a salary of KRW 60-70 million), "
            "depending on whether the field is theoretical or "
            "experimental. The selection process begins with a "
            "letter-of-intent submission (deadline 5 December each "
            "year), followed by invited full research proposals, "
            "reference letters, and an interview — candidates residing "
            "abroad may be evaluated via video conference rather than "
            "in person. Applications are submitted via "
            "https://www.ibs.re.kr/ysf/apply."
        ),
    },
    {
        "title":   "IBS Junior Chief Investigator (Junior CI)",
        "url":     BASE,
        "portal":  "https://www.ibs.re.kr/prog/jci_apply/eng/sub04_04_08/info.do",
        # Letter of intent submission deadline: 5 December each year
        # (joint call with YSF).
        "deadline": datetime.date(2025, 12, 5),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "KRW",
        "sectors": [
            "Mathematics", "Physics", "Chemistry", "Life Sciences",
            "Earth Sciences", "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["KR"],
        "desc": (
            "The IBS Junior Chief Investigator (Junior CI) programme, "
            "launched in 2024, provides a position ensuring research "
            "independence for early-career principal investigators who "
            "have surpassed the Young Scientist Fellowship (YSF) level, "
            "supporting challenging and creative research in basic "
            "science across IBS's 30 Research Centers. The programme is "
            "open to any researcher able to work full-time on research "
            "affiliated with an IBS Research Center, with no nationality "
            "restriction stated; current IBS researchers meeting the "
            "criteria are also eligible. Junior CI appointments run five "
            "years and provide an annual fund of KRW 360-600 million "
            "(including a salary of KRW 80-160 million), depending on "
            "whether the field is theoretical or experimental. "
            "Selection follows the same joint call and process as the "
            "YSF: a letter-of-intent submission (deadline 5 December "
            "each year), invited full research proposals, reference "
            "letters, and an interview, with video-conference evaluation "
            "available for candidates residing abroad. Applications are "
            "submitted via https://www.ibs.re.kr/juniorci/apply."
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
    parser = argparse.ArgumentParser(description="IBS Korea connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  IBS Korea — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  IBS Korea: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
