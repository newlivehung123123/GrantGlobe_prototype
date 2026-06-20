#!/usr/bin/env python3
"""
IOP Pritzker Fellows Program (University of Chicago Institute of Politics)
connector.

The Pritzker Fellows Program brings a cohort of "domestic and international
practitioners — elected officials, journalists, activists, policymakers,
diplomats" to the University of Chicago campus each term for an 8-week,
non-academic residency. The program's own FAQ is explicit on this point:
"This is NOT an academic fellowship. Fellows do not teach a college class
but rather participate in an immersive experience supporting students in
their public service journey through weekly seminars, office hours and
other engagements," and separately confirms "the IOP is an extracurricular
institute on campus and not affiliated with any academic departments."
Selection criteria are the applicant's "background in politics or public
service" and the ability to work well with students and staff — there is
no PhD, university-affiliation, citizenship, or residency requirement
anywhere in the program description or FAQ. Fellows are provided housing
in a hotel or corporate apartment in Hyde Park for the duration of the
residency; the program does not publish a separate cash stipend figure.

This mirrors the eligibility profile of other practitioner-in-residence
programs already in this pipeline (e.g. MIT KSJ, Columbia Knight-Bagehot,
NYU Matthew Power Award), but is centered on politics/public-service
practitioners rather than journalists specifically, and provides in-kind
housing support rather than a cash grant.

The official "Apply to Be a Fellow" page states: "Applications for the
Fall 2026 Fellows Cohort are due on Wednesday, April 1, 2026" — this date
has already passed as of this connector's construction. The program runs
on a recurring termly (Fall / Winter-Spring) cycle, but only the Fall-
cohort deadline is currently published with a specific date, so the
deadline is advanced by one annual cycle (cycle_years=1) under this
pipeline's standard convention, consistent with how single confirmed
annual deadlines have been handled for other recurring fellowship
programs throughout this project.

Source: https://politics.uchicago.edu/fellows/apply-to-be-a-fellow
FAQs:   https://politics.uchicago.edu/uploads/articles/IOP-Pritzker-Fellowship-FAQs.pdf

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/uchicago_pritzker_fellows.py [--dry-run]
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

FUNDER = "Pritzker Fellows Program (Institute of Politics, University of Chicago)"
DOMAIN = "api_uchicago_pritzker_fellows"
SOURCE_URL = "https://politics.uchicago.edu/fellows/apply-to-be-a-fellow"
PORTAL_URL = "https://form.jotform.com/71655655395165"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Pritzker Fellows Program",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "Applications for the Fall 2026 Fellows Cohort are due
        # on Wednesday, April 1, 2026." Already passed at construction.
        "deadline":   datetime.date(2026, 4, 1),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Politics & Public Service", "Journalism", "Civic Engagement"],
        "individual": ["Practitioner", "Policymaker", "Journalist"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "An 8-week, non-academic, on-campus residency for a diverse "
            "cohort of practitioners in politics and public service — "
            "'former elected officials, campaign and policy strategists, "
            "journalists, civic organizers and others' — who lead weekly "
            "seminars, hold office hours, and engage with students at the "
            "University of Chicago. The program's own FAQ is explicit: "
            "'This is NOT an academic fellowship. Fellows do not teach a "
            "college class but rather participate in an immersive "
            "experience supporting students in their public service "
            "journey,' and confirms 'the IOP is an extracurricular "
            "institute on campus and not affiliated with any academic "
            "departments.' Selection is weighted toward applicants who "
            "can tell a compelling story about service, politics, or "
            "policy drawn from their own career — as an aide, reporter, "
            "activist, lawmaker, or similar — with no PhD, university "
            "affiliation, citizenship, or residency requirement of any "
            "kind. Fellows are provided housing in a hotel or corporate "
            "apartment in Hyde Park for the duration of the residency; "
            "no separate cash stipend amount is publicly disclosed. "
            "Cohorts run termly (Fall and Winter-Spring); the Fall cohort "
            "deadline is the only one currently published with a "
            "specific date."
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
    parser = argparse.ArgumentParser(description="UChicago Pritzker Fellows Program connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  UChicago Pritzker Fellows Program — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  UChicago Pritzker Fellows Program: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
