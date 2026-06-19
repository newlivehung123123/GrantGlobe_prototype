#!/usr/bin/env python3
"""
Howard Fellowship (The George A. and Eliza Gardner Howard Foundation,
Brown University) connector.

The Howard Foundation grants yearly, unrestricted fellowships "to assist
in the intellectual and artistic growth of early mid-career individuals."
Fields rotate on a fixed, published multi-year cycle (e.g. 2026-27: Fiction
and Poetry, Literary Studies; 2027-28: Writing for Performance or
Choreography, Theatre, Dance, and Performance Studies; 2028-29: Creative
Nonfiction, History). The official Eligibility Questions page states
plainly: "Normally candidates for a Howard Fellowship will have completed
their formal studies within the past five to fifteen years of the
application date and should also have successfully completed at least one
major project beyond degree requirements that would be sufficient for the
awarding of tenure at higher education institutions or for achieving
comparable peer recognition in creative practice fields, e.g., through
publication or exhibition... Creative practitioners are not required to
hold academic appointments" — i.e. there is no PhD, university affiliation,
or academic appointment requirement of any kind; independent
artists/writers/scholars working outside any institution are explicitly
named as eligible on the same footing as academics, with "comparable peer
recognition in creative practice fields" substituting for a formal academic
credential.

This mirrors the eligibility profile of other practitioner-inclusive
fellowships already in this pipeline (e.g. UCL Liberating the Collections,
AFSEE at LSE), with the distinguishing feature that the Foundation's own
eligibility criteria explicitly waive any academic-appointment requirement
for "creative practitioners" while still permitting independent scholars
to qualify via "comparable peer recognition."

The only non-academic restriction is residency-based, not credential-based:
"Are you, regardless of your citizenship, currently living and working in
the United States or U.S. Territories?" Fellows also confirm the proposed
project falls within that year's announced fields.

Howard Fellowships are unrestricted cash awards of $40,000 (confirmed via
Northwestern University's Office of Research funding-opportunity listing,
which cites "Amount: $40,000. Deadline: 11/1/25" for the current round),
intended solely "for the purpose of aiding the intellectual and artistic
development of the recipients" — there are no service obligations, and the
Foundation does not pay indirect costs.

The official Apply page confirms: "The deadline for this submission of
applications is November 1, 2025. The fellowships funds will be awarded
for use beginning 7/1/2026." This date has already passed as of this
connector's construction. The Sequence of Fields page confirms the program
has run continuously across at least three published consecutive annual
cycles (2026-27, 2027-28, 2028-29, each with its own published 7/1-11/1
application window), so the deadline is advanced by one annual cycle
(cycle_years=1) under this pipeline's standard convention.

Source: https://howard-foundation.brown.edu/eligibility-and-review-process
Apply:  https://howardfoundation.smapply.org/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/brown_howard_foundation.py [--dry-run]
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

FUNDER = "Howard Fellowship (The George A. and Eliza Gardner Howard Foundation, Brown University)"
DOMAIN = "api_brown_howard_foundation"
SOURCE_URL = "https://howard-foundation.brown.edu/eligibility-and-review-process"
PORTAL_URL = "https://howardfoundation.smapply.org/"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Howard Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "The deadline for this submission of applications is
        # November 1, 2025." Already passed at construction.
        "deadline":   datetime.date(2025, 11, 1),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": 40000,
        "amount_max": 40000,
        "sectors":    ["Literature", "Creative Writing", "Theatre & Performance Studies", "Humanities"],
        "individual": ["Practitioner", "Independent Researcher", "Researcher", "Artist"],
        "grant_types": ["Fellowship"],
        "applicant_countries": ["United States"],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "An unrestricted, $40,000 cash fellowship from The George A. "
            "and Eliza Gardner Howard Foundation, an independent agency "
            "administered at Brown University, awarded yearly 'to assist "
            "in the intellectual and artistic growth of early mid-career "
            "individuals.' Fields rotate on a fixed, published multi-year "
            "cycle: 2026-27 (Fiction and Poetry; Literary Studies), "
            "2027-28 (Writing for Performance or Choreography; Theatre, "
            "Dance, and Performance Studies), 2028-29 (Creative "
            "Nonfiction; History). The official Eligibility Questions "
            "page states: 'Normally candidates for a Howard Fellowship "
            "will have completed their formal studies within the past "
            "five to fifteen years of the application date and should "
            "also have successfully completed at least one major project "
            "beyond degree requirements that would be sufficient for the "
            "awarding of tenure at higher education institutions or for "
            "achieving comparable peer recognition in creative practice "
            "fields, e.g., through publication or exhibition... Creative "
            "practitioners are not required to hold academic "
            "appointments' — there is no PhD, university-affiliation, or "
            "academic-appointment requirement of any kind; independent "
            "artists, writers, and scholars working outside any "
            "institution qualify on the same footing as academics via "
            "'comparable peer recognition' in their field. The only "
            "non-academic restriction is residency-based: applicants "
            "must, 'regardless of citizenship,' be currently living and "
            "working in the United States or U.S. Territories. The award "
            "is unrestricted, intended solely 'for the sole purpose of "
            "aiding the intellectual and artistic development of the "
            "recipients,' with no service obligations and no provision "
            "for indirect costs. Required application materials: a "
            "project description (ca. 800-900 words), a two-page CV, a "
            "writing or visual/audio sample, and two letters of "
            "recommendation, submitted via the Foundation's Survey "
            "Monkey Apply portal."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])
    _s.setdefault("focus_countries", [])


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
    parser = argparse.ArgumentParser(description="Brown Howard Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Brown Howard Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Brown Howard Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
