#!/usr/bin/env python3
"""
Austria — Austrian Science Fund (FWF) connector.

FWF is Austria's central public funding body for basic research, and
explicitly states that all FWF grants are open to researchers of any
nationality, provided the project is hosted at an Austrian university
or research institution. This connector covers two of its programmes:

1. FWF Principal Investigator Projects — FWF's core stand-alone
   project-funding instrument, with continuous (rolling) submission
   and no fixed application deadline.

2. FWF ASTRA Awards — a competitive career-funding programme giving
   advanced postdocs in Austria the opportunity to lead independent
   research groups, with five-year awards of EUR 500,000 to EUR
   1,000,000.

Deadline pattern — Principal Investigator Projects uses the
"continuously open" sentinel pattern (as in emergent_ventures.py/
ltff.py); ASTRA Awards uses the annual cyclical-advance pattern (as in
hhmi.py/fli.py).

Source: https://www.fwf.ac.at/en/funding/portfolio/projects/principal-investigator-projects
         https://www.fwf.ac.at/en/funding/portfolio/careers/fwf-astra-awards
Portal: https://elane.fwf.ac.at/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/austria_fwf.py [--dry-run]
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

FUNDER = "Austrian Science Fund (FWF)"
DOMAIN = "api_austria_fwf"
PORTAL = "https://elane.fwf.ac.at/"

SCHEMES: list[dict] = [
    {
        "title":   "FWF Principal Investigator Projects",
        "url":     "https://www.fwf.ac.at/en/funding/portfolio/projects/principal-investigator-projects",
        "portal":  PORTAL,
        # Continuously open — no fixed deadline; modeled with a
        # far-future sentinel, as in emergent_ventures.py/ltff.py.
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "EUR",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["AT"],
        "desc": (
            "FWF Principal Investigator Projects is the Austrian "
            "Science Fund's core stand-alone project-funding "
            "instrument, supporting curiosity-driven basic research "
            "across all disciplines. Applications are accepted "
            "continuously with no fixed deadline, submitted via the "
            "online elane portal. All FWF grants are explicitly open "
            "to researchers of any nationality, provided the project "
            "is carried out at an Austrian university or research "
            "institution. Full guidelines are published at "
            "https://www.fwf.ac.at/en/funding/portfolio/projects/"
            "principal-investigator-projects."
        ),
    },
    {
        "title":   "FWF ASTRA Awards",
        "url":     "https://www.fwf.ac.at/en/funding/portfolio/careers/fwf-astra-awards",
        "portal":  PORTAL,
        # Next confirmed cycle deadline: 15 September 2026 (for the
        # 2027 award cohort).
        "deadline": datetime.date(2026, 9, 15),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Career Development Award"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": 500000,
        "amount_max": 1000000,
        "currency": "EUR",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["AT"],
        "desc": (
            "FWF ASTRA Awards give advanced postdoctoral researchers "
            "in Austria the opportunity to make the leap to leading "
            "their own independent research group. The five-year "
            "awards are endowed with a basic grant of EUR 500,000 to "
            "EUR 1,000,000. As with all FWF programmes, eligibility is "
            "open to researchers of any nationality, provided the "
            "award is hosted at an Austrian university or research "
            "institution. The next confirmed cycle's deadline is 15 "
            "September 2026 (for the 2027 award cohort); subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://www.fwf.ac.at/en/funding/"
            "portfolio/careers/fwf-astra-awards."
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
    parser = argparse.ArgumentParser(description="Austria FWF connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Austria FWF — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Austria FWF: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
