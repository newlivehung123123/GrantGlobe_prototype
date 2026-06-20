#!/usr/bin/env python3
"""
Stanford Humanities Center — Fellowships for External Faculty connector.

The Stanford Humanities Center's External Faculty Fellowship is, per the
source page, "intended primarily for individuals currently teaching in or
affiliated with an academic institution, but independent scholars may
apply" — i.e. open application that explicitly extends beyond traditional
academia to independent (non-academic) scholars, with "no citizenship
requirements." All applicants must hold a PhD and be at least three years
beyond receipt of the degree; fellowships are for one full academic year
in residence at Stanford (mid-September to mid-June).

The source page states exactly: "11:59 PM Pacific Time on October 1,
2025" as the deadline, and separately confirms "The application deadline
for 2026-27 has passed. Check back in August 2026 for the following
academic year" — confirming this is a regular annual cycle. That sourced
date has already passed as of this connector's construction, so it is
advanced by one annual cycle (cycle_years=1) under this pipeline's
standard convention.

Source: https://shc.stanford.edu/stanford-humanities-center/fellowships/fellowships-external-faculty

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/stanford_humanities.py [--dry-run]
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

FUNDER = "Stanford Humanities Center (Stanford University)"
DOMAIN = "api_stanford_humanities"
SOURCE_URL = "https://shc.stanford.edu/stanford-humanities-center/fellowships/fellowships-external-faculty"
PORTAL_URL = "https://shc.stanford.edu/stanford-humanities-center/fellowships/fellowships-external-faculty"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Stanford Humanities Center External Faculty Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: "11:59 PM Pacific Time on October 1, 2025".
        "deadline":   datetime.date(2025, 10, 1),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": 70000,
        "sectors":    ["Humanities", "Interpretive Social Sciences", "Digital Humanities"],
        "individual": ["Researcher", "Faculty", "Independent Scholar"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A full-academic-year (Autumn, Winter, and Spring quarters; "
            "mid-September to mid-June) residential fellowship at the "
            "Stanford Humanities Center for research in the traditional "
            "and emergent disciplines of the humanities and interpretive "
            "social sciences (including digital humanities; creative "
            "arts projects are not eligible). The Center states the "
            "fellowship is 'intended primarily for individuals currently "
            "teaching in or affiliated with an academic institution, but "
            "independent scholars may apply,' with no citizenship "
            "requirements. All applicants must hold a PhD and be at "
            "least three years beyond receipt of the degree at the "
            "start of the fellowship year. Fellows are awarded stipends "
            "of up to $70,000, plus a separate housing and moving "
            "allowance of up to $40,000; the Center does not provide or "
            "finance medical insurance. Awards are made from an "
            "applicant pool of approximately 350."
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
    parser = argparse.ArgumentParser(description="Stanford Humanities Center connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Stanford Humanities Center — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Stanford Humanities Center: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
