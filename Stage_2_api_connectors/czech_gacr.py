#!/usr/bin/env python3
"""
Czech Republic — Czech Science Foundation (GAČR) connector.

GAČR is the Czech Republic's main public funding agency for basic
research. This connector covers three of its annually recurring,
internationally accessible schemes:

1. GAČR Standard Projects — the backbone of basic research funding in
   the Czech Republic, open to all researchers and their teams without
   career-stage limits, hosted at a Czech research institution.

2. GAČR JUNIOR STAR — for excellent early-career scientists (up to 8
   years post-PhD) with significant foreign experience, to gain
   scientific independence and found their own research group.

3. GAČR Postdoc Individual Fellowship (PIF) — Incoming — explicitly
   allows a foreign scientist (or returning Czech postdoc) to come
   carry out research and begin their career at a Czech research
   centre.

(GAČR also runs International Projects with bilateral/Lead Agency
partner agencies — e.g. Taiwan's NSTC, South Korea's NRF, Austria's
FWF, Germany's DFG — which require coordinated submission to two
national agencies and are excluded here as matching the project's
standing bilateral-scheme exclusion. RESTART GRANTS are restricted to
scientists already at Czech institutions returning from a career break
and are not included, since this project is oriented toward
international-access opportunities.)

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://gacr.cz/en/tenders-announced-for-2026-projects/
Portal: https://gacr.cz/en/grant-applications/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/czech_gacr.py [--dry-run]
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

FUNDER = "Czech Science Foundation (GAČR)"
DOMAIN = "api_czech_gacr"
PORTAL = "https://gacr.cz/en/grant-applications/"

SCHEMES: list[dict] = [
    {
        "title":   "GAČR Standard Projects",
        "url":     "https://gacr.cz/en/types-of-grant-projects/",
        "portal":  PORTAL,
        # Annual submission deadline historically falls in early
        # April for the following year's projects (e.g. 3 April 2025
        # for 2026-launching projects); anchored to 3 April 2026 for
        # 2027-launching projects.
        "deadline": datetime.date(2026, 4, 3),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "CZK",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CZ"],
        "desc": (
            "GAČR Standard Projects are the backbone of targeted "
            "support for basic research in the Czech Republic, funding "
            "the best basic research across all fields. Projects "
            "typically run for three years and may be submitted by all "
            "researchers and their teams without limits on career "
            "stage, hosted at a Czech research institution. Each "
            "proposal undergoes review by experts both in the Czech "
            "Republic and abroad. The annual submission deadline "
            "historically falls in early April for the following "
            "year's projects (3 April 2025 for 2026-launching "
            "projects); subsequent cycles follow a similar annual "
            "schedule. Full guidelines are published at "
            "https://gacr.cz/en/tenders-announced-for-2026-projects/."
        ),
    },
    {
        "title":   "GAČR JUNIOR STAR",
        "url":     "https://gacr.cz/en/evaluation-process-of-the-expro-project-proposals/",
        "portal":  PORTAL,
        "deadline": datetime.date(2026, 4, 3),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 25000000,
        "currency": "CZK",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CZ"],
        "desc": (
            "GAČR JUNIOR STAR supports excellent early-career "
            "scientists in basic research (up to 8 years after their "
            "PhD) who have published in prestigious international "
            "journals and have significant foreign experience, giving "
            "them the chance to gain scientific independence and "
            "potentially found their own research group at a Czech "
            "research institution. These are five-year projects with "
            "budgets of up to CZK 25 million, reviewed solely by "
            "external (non-Czech) reviewers. The annual submission "
            "deadline historically falls in early April for the "
            "following year's projects; subsequent cycles follow a "
            "similar annual schedule. Full guidelines are published at "
            "https://gacr.cz/en/tenders-announced-for-2026-projects/."
        ),
    },
    {
        "title":   "GAČR Postdoc Individual Fellowship (PIF) — Incoming",
        "url":     "https://gacr.cz/en/evaluation-process-of-project-proposals/",
        "portal":  PORTAL,
        "deadline": datetime.date(2026, 4, 3),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "CZK",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CZ"],
        "desc": (
            "The GAČR Postdoc Individual Fellowship (PIF) — Incoming "
            "track explicitly allows a foreign scientist (or a "
            "returning Czech postdoc) to come carry out research and "
            "begin their career at a Czech research centre. Eligible "
            "applicants must have completed their doctoral studies "
            "within the past four years. The annual submission "
            "deadline historically falls in early April for the "
            "following year's projects; subsequent cycles follow a "
            "similar annual schedule. Full guidelines are published at "
            "https://gacr.cz/en/tenders-announced-for-2026-projects/."
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
    parser = argparse.ArgumentParser(description="Czech GAČR connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Czech GAČR — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Czech GAČR: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
