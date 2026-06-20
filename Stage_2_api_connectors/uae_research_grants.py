#!/usr/bin/env python3
"""
United Arab Emirates — research grants connector.

This connector covers two verified, internationally accessible UAE
research funding programmes:

1. Al Qasimi Foundation Doctoral Research Grants — fully funded grants
   for PhD students worldwide conducting policy-relevant research on
   Ras Al Khaimah and the wider UAE, run by the Sharjah/Ras
   Al Khaimah-based Al Qasimi Foundation in collaboration with
   internationally recognised universities.

2. Dubai RDI Grants Initiative — a Dubai government applied-research
   funding programme (Cognitive Cities, Health & Life Sciences, and
   Environmental Science), run by the Dubai Future Foundation's Dubai
   Research, Development and Innovation (RDI) programme.

(Qatar's QNRF National Priorities Research Program is open to
international researchers but its 2026 call schedule could not be
verified at the time of writing and is not included here. Israel's ISF
runs only bilateral co-funding collaboration programmes — requiring an
Israeli PI plus a foreign PI each funded by their own country's agency
— matching this project's standing exclusion for matching-fund schemes,
and is also not included.)

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.alqasimifoundation.com/grants-research
         https://dubairdi.ae/
Portal: https://www.alqasimifoundation.com/grants-research
         https://dubairdi.ae/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/uae_research_grants.py [--dry-run]
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

FUNDER_AQF = "Al Qasimi Foundation (UAE)"
FUNDER_RDI = "Dubai Research, Development and Innovation (RDI) Programme"
DOMAIN = "api_uae_research_grants"

SCHEMES: list[dict] = [
    {
        "funder":  FUNDER_AQF,
        "title":   "Al Qasimi Foundation Doctoral Research Grants",
        "url":     "https://www.alqasimifoundation.com/grants-research",
        "portal":  "https://www.alqasimifoundation.com/grants-research",
        # 2026 cycle deadline: 1 April 2026, 23:59 GST (already closed
        # at authoring time).
        "deadline": datetime.date(2026, 4, 1),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Graduate Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Public Policy", "Social Sciences", "Urban Studies",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["AE"],
        "desc": (
            "The Al Qasimi Foundation Doctoral Research Grants fund "
            "PhD students worldwide conducting policy-relevant research "
            "on Ras Al Khaimah and the wider United Arab Emirates, "
            "promoting collaboration among internationally recognised "
            "universities and national UAE institutions. The 2026 "
            "cycle's deadline was 1 April 2026, 23:59 GST; subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://www.alqasimifoundation.com/"
            "grants-research."
        ),
    },
    {
        "funder":  FUNDER_RDI,
        "title":   "Dubai RDI Grants Initiative",
        "url":     "https://dubairdi.ae/",
        "portal":  "https://dubairdi.ae/",
        # 2026 cycle: Letter of Intent deadline 9 June 2026 (already
        # closed at authoring time).
        "deadline": datetime.date(2026, 6, 9),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution", "Company"],
        "amount_min": None,
        "amount_max": None,
        "currency": "AED",
        "sectors": [
            "Cognitive Cities", "Health & Life Sciences",
            "Environmental Science", "Science & Technology",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["AE"],
        "desc": (
            "The Dubai RDI Grants Initiative, run by the Dubai Future "
            "Foundation's Dubai Research, Development and Innovation "
            "programme, funds applied research in Cognitive Cities, "
            "Health & Life Sciences, and Environmental Science, aimed "
            "at strengthening Dubai's applied research ecosystem. The "
            "2026 cycle's Letter of Intent deadline was 9 June 2026; "
            "subsequent cycles follow a similar annual schedule. Full "
            "guidelines are published at https://dubairdi.ae/."
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
    parser = argparse.ArgumentParser(description="UAE research grants connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  UAE Research Grants — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  UAE Research Grants: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
