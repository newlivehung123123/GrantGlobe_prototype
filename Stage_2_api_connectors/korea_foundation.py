#!/usr/bin/env python3
"""
Korea Foundation (KF) connector.

The Korea Foundation is the Republic of Korea's public diplomacy
institution, promoting Korean Studies and international understanding of
Korea worldwide. Among its programmes (Korean Studies course support,
global networking, arts and cultural exchange), this connector covers its
three research-relevant Fellowship Program categories aimed at overseas
scholars — directly matching this codebase's interest in "funders in
[the host country] funding foreigners to conduct [host-country-related]
research," as established with Taiwan's CCKF and Taiwan Fellowship
connectors:

1. Scholarship for Graduate Studies (GS) — for graduate students at a
   university outside Korea pursuing a Korea-related research topic.

2. Fellowship for Postdoctoral Research (PF) — for scholars who have
   recently obtained a PhD with a Korea-related research topic, to
   conduct full-time research at a university or institution outside
   Korea. Notably, this fellowship explicitly excludes applicants from
   North America, Europe, and Japan.

3. Fellowship for Field Research (FR) — for overseas Korean studies
   scholars and experts to conduct on-site field research in Korea
   (approximately 30 fellowships per year).

(KF's Korean Language and Culture Program for Diplomats is also part of
the Fellowship Program family but is restricted to applications via
Korean diplomatic missions and is not covered here.)

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).
GS and PF are announced jointly each year; FR is announced separately
with a slightly earlier deadline.

Source: https://www.kf.or.kr/kfEng/cm/cntnts/cntntsView.do?mi=15556&cntntsId=2182
Portal: https://apply.kf.or.kr/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/korea_foundation.py [--dry-run]
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

FUNDER = "Korea Foundation (KF)"
DOMAIN = "api_korea_foundation"
BASE   = "https://www.kf.or.kr/kfEng/cm/cntnts/cntntsView.do?mi=15556&cntntsId=2182"
PORTAL = "https://apply.kf.or.kr/"

SCHEMES: list[dict] = [
    {
        "title":   "KF Scholarship for Graduate Studies (GS)",
        "url":     BASE,
        "portal":  PORTAL,
        # 2025-2026 cycle: application period closed 12 September 2025
        # (already closed at authoring time).
        "deadline": datetime.date(2025, 9, 12),
        "open_threshold_days": 55,        # application window opens ~21 July
        "cycle_years": 1,
        "grant_types": ["Graduate Scholarship"],
        "individual": ["Graduate Student", "PhD Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Korean Studies", "Area Studies", "Humanities",
            "Social Sciences", "Arts & Cultural Studies",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["KR"],
        "desc": (
            "The KF Scholarship for Graduate Studies (GS) provides "
            "scholarship support to M.A. students or PhD candidates in "
            "the humanities, social sciences, arts and cultural studies, "
            "or other relevant fields, with a Korea-related research "
            "topic, at a university located outside Korea. The "
            "scholarship covers a one-year period. Program announcements "
            "are made each year with the latest application details; "
            "the 2025-2026 cycle's application period ran from 21 July "
            "to 12 September 2025. Applications are submitted online via "
            "the KF Application Portal at https://apply.kf.or.kr/. "
            "Inquiries: scholarship@kf.or.kr."
        ),
    },
    {
        "title":   "KF Fellowship for Postdoctoral Research (PF)",
        "url":     BASE,
        "portal":  PORTAL,
        # Announced jointly with GS each year; 2025-2026 cycle deadline
        # 12 September 2025 (already closed at authoring time).
        "deadline": datetime.date(2025, 9, 12),
        "open_threshold_days": 55,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Korean Studies", "Area Studies", "Humanities",
            "Social Sciences", "Arts & Cultural Studies",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["KR"],
        "desc": (
            "The KF Fellowship for Postdoctoral Research (PF) supports "
            "the full-time research of emerging scholars who have "
            "recently obtained a PhD with a Korea-related research "
            "topic in the humanities, social sciences, arts and "
            "cultural studies, media and communications, or contemporary "
            "Korean studies, at a university or research institution "
            "located outside Korea. Notably, this fellowship is open to "
            "scholars from all nations except North America, Europe, and "
            "Japan. The fellowship period is one year, beginning in "
            "Spring or Fall, with a stipend determined by the project "
            "proposal and regional circumstances. PF is announced "
            "jointly with the Scholarship for Graduate Studies each "
            "year; the 2025-2026 cycle's application period ran from 21 "
            "July to 12 September 2025. Applications are submitted "
            "online via the KF Application Portal at "
            "https://apply.kf.or.kr/. Inquiries: scholarship@kf.or.kr."
        ),
    },
    {
        "title":   "KF Fellowship for Field Research (FR)",
        "url":     "https://www.kf.or.kr/kfEng/cm/cntnts/cntntsView.do?mi=2222&cntntsId=1677",
        "portal":  PORTAL,
        # 2026 cycle: application deadline 1 September 2025, 6:00pm KST
        # (already closed at authoring time).
        "deadline": datetime.date(2025, 9, 1),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Field Research Fellowship"],
        "individual": ["PhD Student", "Senior Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "KRW",
        "sectors": [
            "Korean Studies", "Area Studies", "Humanities",
            "Social Sciences", "Arts & Cultural Studies",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["KR"],
        "desc": (
            "The KF Fellowship for Field Research (FR) provides eminent "
            "overseas Korean studies scholars and experts in relevant "
            "fields with the opportunity to conduct on-site field "
            "research in Korea and access relevant resource materials. "
            "Eligible applicants are overseas researchers working in the "
            "humanities, social sciences, or arts and culture, either "
            "conducting comparative or case studies in Korean studies or "
            "Korea-related areas, or researching topics closely related "
            "to Korea recognised as important new areas of study. There "
            "are two support types: Type A for doctoral candidates "
            "working on a dissertation after completing coursework "
            "(monthly stipend KRW 2,300,000), and Type B for university "
            "professors (full-time lecturer rank or higher) or "
            "researchers with a doctorate (monthly stipend KRW "
            "3,000,000). Fellowships run 1 to 6 months, with "
            "approximately 30 fellowships awarded per year, plus "
            "round-trip airfare for fellows whose country of residence "
            "is on the OECD Development Assistance Committee's list of "
            "ODA recipients. The 2026 cycle's application deadline was 1 "
            "September 2025, 6:00pm Korea Standard Time; subsequent "
            "cycles follow a similar annual schedule. Applications are "
            "submitted online via the KF Application Portal at "
            "https://apply.kf.or.kr/. Inquiries: fellow@kf.or.kr."
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
    parser = argparse.ArgumentParser(description="Korea Foundation connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Korea Foundation — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Korea Foundation: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
