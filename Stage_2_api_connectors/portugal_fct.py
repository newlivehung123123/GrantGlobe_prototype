#!/usr/bin/env python3
"""
Portugal — Fundação para a Ciência e a Tecnologia (FCT) connector.

FCT is Portugal's main public research funding agency. This connector
covers two of its largest recurring annual calls:

1. FCT PhD Research Scholarships in All Scientific Domains — FCT's
   flagship doctoral scholarship call, with two application lines
   (General and Non-Academic Environment).

2. FCT R&D Projects in All Scientific Domains — funds SR&TD (up to
   EUR 250,000 over 36 months) and PEX exploratory (up to EUR 60,000
   over 18 months) project types, hosted at a Portuguese R&D unit.

(FCT separately ran an "FCT Mobility" programme funding incoming and
outgoing PhD researcher exchanges, but this was a fixed EUR 5 million
allocation under the EU Recovery and Resilience Plan with applications
closing 31 December 2025 and is not confirmed to recur as a standing
annual programme; it is not included here.)

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.fct.pt/en/financiamento/programas-de-financiamento/
Portal: https://www.fct.pt/en/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/portugal_fct.py [--dry-run]
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

FUNDER = "Fundação para a Ciência e a Tecnologia (FCT), Portugal"
DOMAIN = "api_portugal_fct"
BASE   = "https://www.fct.pt/en/financiamento/programas-de-financiamento/"
PORTAL = "https://www.fct.pt/en/"

SCHEMES: list[dict] = [
    {
        "title":   "FCT PhD Research Scholarships in All Scientific Domains",
        "url":     "https://www.fct.pt/en/financiamento/programas-de-financiamento/bolsas-de-doutoramento/",
        "portal":  PORTAL,
        # 2026 cycle: applications 2-31 March 2026 (already closed at
        # authoring time).
        "deadline": datetime.date(2026, 3, 31),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "grant_types": ["PhD Scholarship"],
        "individual": ["Graduate Student"],
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
        "focus_countries": ["PT"],
        "desc": (
            "The FCT PhD Research Scholarships in All Scientific "
            "Domains is FCT's flagship doctoral funding call, awarding "
            "1,600 scholarships with a total budget of EUR 145 "
            "million across two application lines: the General "
            "Application Line (1,000 scholarships, EUR 90.6 million) "
            "and the Non-Academic Environment Application Line (600 "
            "scholarships, EUR 54.4 million). The 2026 cycle's "
            "application window ran from 2 to 31 March 2026; "
            "subsequent cycles follow a similar annual schedule. Full "
            "guidelines are published at https://www.fct.pt/en/"
            "financiamento/programas-de-financiamento/."
        ),
    },
    {
        "title":   "FCT R&D Projects in All Scientific Domains",
        "url":     "https://www.fct.pt/en/financiamento/programas-de-financiamento/projetos-id/projetos-em-todos-os-dominios-cientificos/",
        "portal":  PORTAL,
        # 2026 cycle: open 27 November 2025, deadline 11 March 2026
        # (already closed at authoring time).
        "deadline": datetime.date(2026, 3, 11),
        "open_threshold_days": 105,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 250000,
        "currency": "EUR",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["PT"],
        "desc": (
            "FCT R&D Projects in All Scientific Domains funds two "
            "project types hosted at Portuguese R&D units: SR&TD "
            "projects, receiving up to EUR 250,000 over 36 months, and "
            "PEX exploratory projects, receiving up to EUR 60,000 over "
            "18 months. The 2026 cycle opened 27 November 2025 with a "
            "deadline of 11 March 2026; subsequent cycles follow a "
            "similar annual schedule. Full guidelines are published at "
            "https://www.fct.pt/en/financiamento/programas-de-"
            "financiamento/projetos-id/projetos-em-todos-os-dominios-"
            "cientificos/."
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
    parser = argparse.ArgumentParser(description="Portugal FCT connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Portugal FCT — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Portugal FCT: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
