#!/usr/bin/env python3
"""
Knight Science Journalism Fellowship (MIT) connector.

The Knight Science Journalism (KSJ) Program at MIT offers a nine-and-a-
half-month Academic-Year Fellowship to science journalists from around
the globe. Eligibility is restricted to "full-time journalists, whether
on staff or freelance" with at least three consecutive years of
experience covering science, health, technology, or environmental
reporting — i.e. this is explicitly a working-professional / non-
academic fellowship, not restricted (or even open) to university-
affiliated academics; no PhD or academic appointment is required or
expected.

The source page states exactly: "Applications for 2026-2027 fellowship
class will open on November 15, 2025 and close on January 9, 2026," and
separately: "Both the Academic-Year Fellowship and the Africa and Middle
East Fellowship will accept applications until January 9, 2026." That
date has already passed as of this connector's construction, so it is
advanced by one annual cycle (cycle_years=1) under this pipeline's
standard convention; the page confirms this is a regular annual cycle
("Every year, the Knight Science Journalism Program at MIT offers
academic-year fellowships to 10 science journalists from around the
globe").

Source: https://ksj.mit.edu/fellowships/academic-year-fellowship/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/mit_ksj.py [--dry-run]
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

FUNDER = "Knight Science Journalism Program (Massachusetts Institute of Technology)"
DOMAIN = "api_mit_ksj"
SOURCE_URL = "https://ksj.mit.edu/fellowships/academic-year-fellowship/"
PORTAL_URL = "https://ksj.submittable.com/submit/666096d6-6809-49d5-aa55-eea3eba30768/ksj-academic-year-fellowship-2026-2027"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Knight Science Journalism Academic-Year Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: applications "close on January 9, 2026" for
        # the 2026-27 fellowship class; that date had already passed at
        # construction.
        "deadline":   datetime.date(2026, 1, 9),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": 85000,
        "sectors":    ["Science Journalism", "Science Communication"],
        "individual": ["Journalist", "Practitioner"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A nine-and-a-half-month, full-time residential fellowship "
            "at MIT for working science journalists, offering the "
            "opportunity to pursue a journalism-related research "
            "project, audit courses at MIT and Harvard, and take part "
            "in seminars, field trips, and skills workshops in the "
            "Cambridge/Boston area. Eligibility is restricted to "
            "full-time journalists (staff or freelance) with at least "
            "three consecutive years of experience covering science, "
            "health, technology, or environmental reporting — an "
            "explicitly non-academic, working-professional fellowship "
            "with no PhD or university affiliation required. "
            "International candidates are encouraged to apply (with "
            "MIT sponsoring the necessary J-1/J-2 visas). Fellows "
            "receive an $85,000 stipend paid over 9.5 months, a one-"
            "time travel and housing stipend near the start of the "
            "fellowship, and basic health insurance for the fellow and "
            "their family."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])
    _s.setdefault("focus_countries", ['US'])


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
    """Advance est by cycle_years until it is in the future."""
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
        "application_deadline_raw":  deadline.strftime("%d %B %Y"),
        "grant_opening_date":        opening.isoformat(),
        "current_status":            status,
        "source_language":           "en",
        "funding_amount_min":        scheme["amount_min"],
        "funding_amount_max":        scheme["amount_max"],
        "currency":                  scheme["currency"],
        "thematic_sectors":          scheme["sectors"],
        "grant_types":               scheme["grant_types"],
        "applicant_base_regions":    ["Global"],
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
        # internal — stripped before DB write
        "_days_until": days_until,
    }


# ---------------------------------------------------------------------------
# DB upsert (composite key: source_url + grant_title)
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    db_rec = {k: v for k, v in record.items() if not k.startswith("_")}
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s AND grant_title = %s",
                (db_rec["source_url"], db_rec["grant_title"]))
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
    parser = argparse.ArgumentParser(description="MIT Knight Science Journalism connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  MIT Knight Science Journalism — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  MIT Knight Science Journalism: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
