#!/usr/bin/env python3
"""
Denmark — Independent Research Fund Denmark (Danmarks Frie
Forskningsfond, DFF) connector.

DFF is Denmark's main public fund for independent (curiosity-driven)
research across all disciplines. This connector covers its two main
recurring project grant instruments:

1. DFF Research Project1 — for researchers who obtained their PhD (or
   equivalent) at least 3 years before the deadline.

2. DFF Research Project2 — a larger, more ambitious instrument that can
   include PhD and postdoctoral components.

(Applicants may submit a maximum of one DFF application per year, and
may not apply for new DFF funding if currently holding two or more
active DFF grants. Eligibility is tied to being hosted at a Danish
research institution rather than to Danish citizenship.)

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://dff.dk/en/apply-for-funding/see-what-you-can-apply-for/current-funding-opportunities/
Portal: https://dff.dk/en/apply-for-funding/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/denmark_dff.py [--dry-run]
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

FUNDER = "Independent Research Fund Denmark (DFF)"
DOMAIN = "api_denmark_dff"
BASE   = "https://dff.dk/en/apply-for-funding/see-what-you-can-apply-for/current-funding-opportunities/"
PORTAL = "https://dff.dk/en/apply-for-funding/"

SCHEMES: list[dict] = [
    {
        "title":   "DFF Research Project1",
        "url":     BASE,
        "portal":  PORTAL,
        # 2026 cycle deadline: 12 May 2026 (already closed at authoring
        # time).
        "deadline": datetime.date(2026, 5, 12),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher", "Senior Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 2550000,
        "currency": "DKK",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["DK"],
        "desc": (
            "DFF Research Project1 supports ambitious, independent "
            "research projects across all disciplines, providing up to "
            "DKK 2,550,000 excluding overhead. Applicants must have "
            "obtained their PhD degree or equivalent qualifications at "
            "least three years before the application deadline, and "
            "must be hosted at a Danish research institution. "
            "Applicants may submit a maximum of one DFF application "
            "per year, and may not apply for new DFF funding while "
            "holding two or more active DFF grants. The 2026 cycle's "
            "deadline was 12 May 2026; subsequent cycles follow a "
            "similar annual schedule. Full guidelines are published at "
            "https://dff.dk/en/apply-for-funding/see-what-you-can-"
            "apply-for/current-funding-opportunities/."
        ),
    },
    {
        "title":   "DFF Research Project2",
        "url":     BASE,
        "portal":  PORTAL,
        # 2026 cycle deadline: 7 October 2026 (already closed at
        # authoring time).
        "deadline": datetime.date(2026, 10, 7),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": 2550000,
        "amount_max": 4450000,
        "currency": "DKK",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["DK"],
        "desc": (
            "DFF Research Project2 supports larger, more ambitious "
            "independent research initiatives, providing between DKK "
            "2,550,000 and DKK 4,450,000, including the option of PhD "
            "and postdoctoral components. Applicants must be hosted at "
            "a Danish research institution. Applicants may submit a "
            "maximum of one DFF application per year, and may not "
            "apply for new DFF funding while holding two or more "
            "active DFF grants. The 2026 cycle's deadline was 7 "
            "October 2026; subsequent cycles follow a similar annual "
            "schedule. Full guidelines are published at "
            "https://dff.dk/en/apply-for-funding/see-what-you-can-"
            "apply-for/current-funding-opportunities/."
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
    parser = argparse.ArgumentParser(description="Denmark DFF connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Denmark DFF — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Denmark DFF: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
