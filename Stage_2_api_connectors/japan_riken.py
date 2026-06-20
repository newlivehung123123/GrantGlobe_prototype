#!/usr/bin/env python3
"""
RIKEN (Japan) connector — Special Postdoctoral Researchers Program (SPDR)
and International Program Associate (IPA).

RIKEN is Japan's largest comprehensive research institution. This
connector covers two of its international "Programs for Junior
Scientists" that are explicitly open to non-Japanese researchers (the
PI-level RIKEN ECL and Hakubi Fellows programmes are standard faculty-type
recruitment rather than competitive fellowships, and are not covered
here):

1. Special Postdoctoral Researchers (SPDR) Program — for Japanese and
   non-Japanese postdoctoral researchers with a PhD in the natural
   sciences awarded less than 5 years prior, to conduct independent
   research at RIKEN for a standard three-year term.

2. International Program Associate (IPA) — for non-Japanese doctoral
   candidates enrolled at a Japanese or overseas university that has a
   joint graduate-school partnership agreement with RIKEN (partner
   universities span China, Hong Kong, Taiwan, Korea, India, Pakistan,
   Indonesia, Malaysia, Vietnam, Thailand, the Philippines, Australia,
   Russia, Ukraine, the UK, Germany, Spain, Canada, Brazil, Egypt, and
   Nigeria, among others), to conduct PhD research at RIKEN for 1-3
   years. Calls for applications from overseas universities are issued
   twice yearly, in April and September.

Deadline pattern — annual cycle for SPDR; two recruitment windows per
year for IPA (both modelled using the cyclical-advance pattern, as in
hhmi.py/fli.py).

Source: https://www.riken.jp/en/careers/programs/
Portal: https://www.riken.jp/en/careers/programs/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/japan_riken.py [--dry-run]
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

FUNDER = "RIKEN (Japan)"
DOMAIN = "api_japan_riken"
BASE   = "https://www.riken.jp/en/careers/programs/"
PORTAL = "https://www.riken.jp/en/careers/programs/"

SCHEMES: list[dict] = [
    {
        "title":   "RIKEN Special Postdoctoral Researchers Program (SPDR)",
        "url":     "https://www.riken.jp/en/careers/programs/spdr/index.html",
        "portal":  PORTAL,
        # Annual application deadline: 2 April.
        "deadline": datetime.date(2026, 4, 2),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "JPY",
        "sectors": [
            "Physics", "Chemistry", "Life Sciences", "Health Sciences",
            "Engineering", "Science & Technology",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Japan"],
        "desc": (
            "The RIKEN Special Postdoctoral Researchers (SPDR) Program "
            "invites outstanding scientists — Japanese and non-Japanese "
            "alike — to contribute to RIKEN's research and help lay the "
            "foundations for a globalised RIKEN, in physics, chemistry, "
            "biology, medical science, or engineering. Applicants must "
            "hold a PhD in the natural sciences awarded less than 5 "
            "years prior to the year of the call (exceptions considered "
            "individually for justified research breaks). Successful "
            "candidates receive an annual salary paid in monthly "
            "installments (approximately 487,000 yen per month, "
            "inclusive of social insurance and taxes), a commuting "
            "allowance, and a housing allowance. The standard contract "
            "duration is three years, usually beginning in the relevant "
            "fiscal year. Document screening and interviews follow the "
            "application deadline of 2 April each year. Full guidelines "
            "are published at "
            "https://www.riken.jp/en/careers/programs/spdr/."
        ),
    },
    {
        "title":   "RIKEN International Program Associate (IPA) — April Intake",
        "url":     "https://www.riken.jp/en/careers/programs/ipa/index.html",
        "portal":  PORTAL,
        # Biannual call: April.
        "deadline": datetime.date(2026, 4, 30),
        "deadline_raw": "Call issued in April (exact deadline set per call)",
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["PhD Fellowship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "JPY",
        "sectors": [
            "Physics", "Chemistry", "Life Sciences", "Health Sciences",
            "Engineering", "Science & Technology",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Japan"],
        "desc": (
            "An International Program Associate (IPA) is a non-Japanese "
            "doctoral candidate enrolled at a Japanese or overseas "
            "graduate school that has entered into a joint graduate "
            "school partnership agreement with RIKEN (partner "
            "universities span mainland China, Hong Kong, Taiwan, "
            "Korea, India, Pakistan, Indonesia, Malaysia, Vietnam, "
            "Thailand, the Philippines, Australia, Russia, Ukraine, the "
            "UK, Germany, Spain, Canada, Brazil, Egypt, and Nigeria, "
            "among others). IPAs conduct PhD research at RIKEN under the "
            "supervision of RIKEN scientists, for 1 to 3 years, with a "
            "starting date selectable from October-April or April-"
            "October. RIKEN provides a living allowance of 5,200 yen "
            "per day, free or subsidised housing (up to 70,000 yen per "
            "month off-campus), one round-trip airfare, and accident "
            "insurance. For candidates applying from outside Japan, "
            "calls for applications are issued twice yearly, in April "
            "and September; applicants must first contact a RIKEN "
            "researcher of interest before applying. Full guidelines and "
            "the current list of partner universities are published at "
            "https://www.riken.jp/en/careers/programs/ipa/."
        ),
    },
    {
        "title":   "RIKEN International Program Associate (IPA) — September Intake",
        "url":     "https://www.riken.jp/en/careers/programs/ipa/index.html",
        "portal":  PORTAL,
        # Biannual call: September.
        "deadline": datetime.date(2026, 9, 30),
        "deadline_raw": "Call issued in September (exact deadline set per call)",
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["PhD Fellowship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "JPY",
        "sectors": [
            "Physics", "Chemistry", "Life Sciences", "Health Sciences",
            "Engineering", "Science & Technology",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Japan"],
        "desc": (
            "An International Program Associate (IPA) is a non-Japanese "
            "doctoral candidate enrolled at a Japanese or overseas "
            "graduate school that has entered into a joint graduate "
            "school partnership agreement with RIKEN (partner "
            "universities span mainland China, Hong Kong, Taiwan, "
            "Korea, India, Pakistan, Indonesia, Malaysia, Vietnam, "
            "Thailand, the Philippines, Australia, Russia, Ukraine, the "
            "UK, Germany, Spain, Canada, Brazil, Egypt, and Nigeria, "
            "among others). IPAs conduct PhD research at RIKEN under the "
            "supervision of RIKEN scientists, for 1 to 3 years, with a "
            "starting date selectable from October-April or April-"
            "October. RIKEN provides a living allowance of 5,200 yen "
            "per day, free or subsidised housing (up to 70,000 yen per "
            "month off-campus), one round-trip airfare, and accident "
            "insurance. For candidates applying from outside Japan, "
            "calls for applications are issued twice yearly, in April "
            "and September; applicants must first contact a RIKEN "
            "researcher of interest before applying. Full guidelines and "
            "the current list of partner universities are published at "
            "https://www.riken.jp/en/careers/programs/ipa/."
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
    parser = argparse.ArgumentParser(description="RIKEN connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  RIKEN — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  RIKEN: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
