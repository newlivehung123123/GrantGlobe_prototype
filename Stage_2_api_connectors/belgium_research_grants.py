#!/usr/bin/env python3
"""
Belgium — research grants connector (FWO Flanders + F.R.S.-FNRS Wallonia).

Belgium's public research funding is split by region/community, each
with its own funding agency. This connector covers the verified,
internationally accessible programmes of both:

1. FWO (Research Foundation Flanders) PhD Fellowship Fundamental
   Research — for early-career researchers (up to 18 months of
   scientific seniority) to prepare a PhD, hosted at a Flemish
   institution.

2. FWO Junior and Senior Research Projects — FWO's core competitive
   research-project instrument for teams of leading researchers,
   running up to four years.

3. FWO Grant for a Scientific Stay in Flanders — a rolling-deadline
   mobility grant explicitly for postdoctoral researchers affiliated
   with a non-Belgian research institution to spend 1-3 months in
   Flanders.

4. F.R.S.-FNRS International Projects (PINT) — for international
   collaborative research projects, providing up to EUR 300,000 over
   three years, hosted in the Wallonia-Brussels Federation.

Deadline pattern — FWO PhD Fellowship, FWO Junior/Senior Research
Project, and FNRS PINT use the annual cyclical-advance pattern (as in
hhmi.py/fli.py); the FWO Grant for a Scientific Stay in Flanders uses
the "continuously open" sentinel pattern (as in emergent_ventures.py/
ltff.py), since applications are accepted on a rolling basis at least
three months before the intended stay.

Source: https://www.fwo.be/en/support-programmes/all-calls/
         https://www.frs-fnrs.be/en/fundings
Portal: https://www.fwo.be/en/
         https://www.frs-fnrs.be/en/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/belgium_research_grants.py [--dry-run]
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

FUNDER_FWO = "Research Foundation Flanders (FWO)"
FUNDER_FNRS = "Fund for Scientific Research (F.R.S.-FNRS), Belgium"
DOMAIN = "api_belgium_research_grants"

FWO_BASE = "https://www.fwo.be/en/support-programmes/all-calls/"
FNRS_BASE = "https://www.frs-fnrs.be/en/fundings"

SCHEMES: list[dict] = [
    {
        "funder":  FUNDER_FWO,
        "title":   "FWO PhD Fellowship Fundamental Research",
        "url":     "https://www.fwo.be/en/support-programmes/all-calls/phd/phd-fellowship-fundamental-research/",
        "portal":  FWO_BASE,
        # 2026 cycle deadline: 2 March 2026, 17:00 CET (already closed
        # at authoring time).
        "deadline": datetime.date(2026, 3, 2),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["PhD Fellowship"],
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
        "focus_countries": ["BE"],
        "desc": (
            "The FWO PhD Fellowship Fundamental Research allows young "
            "researchers to prepare a PhD and develop into independent "
            "scientists with a critical mindset, hosted at a Flemish "
            "research institution. Applicants may have a maximum of "
            "18 months of scientific seniority at the deadline, and "
            "may apply at most twice for this fellowship. The 2026 "
            "cycle's deadline was 2 March 2026, 17:00 CET; subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://www.fwo.be/en/support-"
            "programmes/all-calls/phd/phd-fellowship-fundamental-"
            "research/."
        ),
    },
    {
        "funder":  FUNDER_FWO,
        "title":   "FWO Junior and Senior Research Project",
        "url":     "https://www.fwo.be/en/support-programmes/all-calls/senior-researchersresearch-teams/junior-and-senior-research-project/",
        "portal":  FWO_BASE,
        # 2026 cycle deadline: 1 April 2026, 17:00 CET (already closed
        # at authoring time; call opened 15 January 2026).
        "deadline": datetime.date(2026, 4, 1),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "EUR",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences", "Biomedical Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["BE"],
        "desc": (
            "FWO Junior and Senior Research Projects give teams of "
            "leading researchers the opportunity to set up medium- to "
            "large-scale basic, strategic basic, or applied biomedical "
            "research actions over up to four years, hosted at a "
            "Flemish research institution. The 2026 cycle opened 15 "
            "January 2026 with a submission deadline of 1 April 2026, "
            "17:00 CET; subsequent cycles follow a similar annual "
            "schedule. Full guidelines are published at "
            "https://www.fwo.be/en/support-programmes/all-calls/"
            "senior-researchersresearch-teams/junior-and-senior-"
            "research-project/."
        ),
    },
    {
        "funder":  FUNDER_FWO,
        "title":   "FWO Grant for a Scientific Stay in Flanders",
        "url":     "https://www.fwo.be/en/support-programmes/all-calls/mobility/grant-for-a-scientific-stay-in-flanders/",
        "portal":  FWO_BASE,
        # Rolling deadline — applications must be submitted at least
        # three months before the intended stay; modeled with a
        # far-future sentinel, as in emergent_ventures.py/ltff.py.
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,
        "cycle_years": 1,
        "grant_types": ["Mobility Grant"],
        "individual": ["Postdoctoral Researcher"],
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
        "focus_countries": ["BE"],
        "desc": (
            "The FWO Grant for a Scientific Stay in Flanders is a "
            "travel grant explicitly for postdoctoral researchers "
            "affiliated with a non-Belgian research institution, "
            "supporting a scientific stay in Flanders of one to three "
            "months without interruption. Applications must be "
            "submitted online in English at least three months before "
            "the date of departure; a host researcher can receive only "
            "one grantee per calendar year. Applications are accepted "
            "on a rolling basis throughout the year. Full guidelines "
            "are published at https://www.fwo.be/en/support-"
            "programmes/all-calls/mobility/grant-for-a-scientific-"
            "stay-in-flanders/."
        ),
    },
    {
        "funder":  FUNDER_FNRS,
        "title":   "F.R.S.-FNRS International Projects (PINT)",
        "url":     "https://www.frs-fnrs.be/en/financements/projets-internationaux-pint",
        "portal":  FNRS_BASE,
        # 2026 cycle: administrative pre-proposal deadline 17 February
        # 2026, 14:00 CET (already closed at authoring time).
        "deadline": datetime.date(2026, 2, 17),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 300000,
        "currency": "EUR",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["BE"],
        "desc": (
            "F.R.S.-FNRS International Projects (PINT) fund "
            "international collaborative research projects led from "
            "the Wallonia-Brussels Federation, providing up to EUR "
            "300,000 per project over a maximum of three years. The "
            "2026 cycle's administrative pre-proposal deadline (via "
            "the e-space platform) was 17 February 2026, 14:00 CET; "
            "subsequent cycles follow a similar annual schedule. Full "
            "guidelines are published at "
            "https://www.frs-fnrs.be/en/financements/projets-"
            "internationaux-pint."
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
        "funder_name":               scheme["funder"],
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
    parser = argparse.ArgumentParser(description="Belgium research grants connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Belgium Research Grants — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Belgium Research Grants: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
