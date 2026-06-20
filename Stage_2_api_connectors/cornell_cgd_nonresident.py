#!/usr/bin/env python3
"""
Non-Resident Fellowship Program (Cornell Brooks School of Public Policy,
Center on Global Democracy) connector.

The CGD Non-Resident Fellowship Program is a one-year, non-residential
fellowship "designed for academics and practitioners to engage in
research on democracy and policy." The official "Who is eligible?"
section states plainly: "We are looking for scholars and policymakers/
practitioners who are working on research related to the CGD mission" —
i.e. policymakers and practitioners are named alongside academic scholars
as equally eligible applicant categories, with no PhD or university-
affiliation requirement of any kind. Fellows engage on annual research
themes (for 2025-2026: civic education and citizens' democratic
engagement; crisis, governance, and development; democracy and
technology; democracy and climate; democratic backsliding, resilience,
and resistance; and media, political communications, political
psychology, and democracy).

This mirrors the eligibility profile of other dual-track practitioner/
academic fellowships already in this pipeline (e.g. AFSEE at LSE, CASI at
UPenn), with the distinguishing feature that CGD's own published
eligibility criteria name "policymakers/practitioners" directly alongside
"scholars" as a single, undifferentiated applicant pool (rather than as a
separate track with its own threshold).

Fellows receive a $2,000 stipend (paid upon completion), guaranteed
research assistance (20 hours per semester from CGD's undergraduate
research assistants), access to the DARE (Democratic Attacks and
Resistance Events) datasets, and support disseminating research through
CGD's communications channels (policy briefs, podcasts, social media,
infographics). In exchange, Fellows are expected to participate in CGD
conferences/seminars/workshops, produce two CGD Policy Briefs and two
media-outreach pieces, collaborate on an ongoing CGD research project,
and participate in one CGD service activity.

The official timeline confirms: "CFP August – September 2025. Deadline
for applications: September 30, 2025. Selection and start of Fellowship:
October 15, 2025" (fellowship term: October 15, 2025 – October 14, 2026).
This date has already passed as of this connector's construction. The
program is structured as an annually recurring fellowship built around a
yearly CFP and a fresh set of annual research themes, so the deadline is
advanced by one annual cycle (cycle_years=1) under this pipeline's
standard convention.

Source: https://publicpolicy.cornell.edu/cgd/opportunities/non-resident-fellowship-program/
Apply:  https://docs.google.com/forms/d/e/1FAIpQLSfWgM8t-qOKqvUTjcCrsS6DzIn9GNMQk8Wl2JqCedbzfwZWyA/viewform

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/cornell_cgd_nonresident.py [--dry-run]
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

FUNDER = "Center on Global Democracy Non-Resident Fellowship Program (Cornell Brooks School of Public Policy)"
DOMAIN = "api_cornell_cgd_nonresident"
SOURCE_URL = "https://publicpolicy.cornell.edu/cgd/opportunities/non-resident-fellowship-program/"
PORTAL_URL = "https://docs.google.com/forms/d/e/1FAIpQLSfWgM8t-qOKqvUTjcCrsS6DzIn9GNMQk8Wl2JqCedbzfwZWyA/viewform"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Center on Global Democracy (CGD) Non-Resident Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "Deadline for applications: September 30, 2025."
        # Already passed at construction.
        "deadline":   datetime.date(2025, 9, 30),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": 2000,
        "amount_max": 2000,
        "sectors":    ["Democracy & Governance", "Public Policy", "Political Science"],
        "individual": ["Practitioner", "Policymaker", "Researcher"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A one-year, non-residential fellowship at the Center on "
            "Global Democracy (CGD), Cornell Jeb E. Brooks School of "
            "Public Policy, 'designed for academics and practitioners to "
            "engage in research on democracy and policy.' The official "
            "eligibility section states: 'We are looking for scholars "
            "and policymakers/practitioners who are working on research "
            "related to the CGD mission' — there is no PhD or "
            "university-affiliation requirement of any kind. Annual "
            "research themes (2025-2026) include civic education and "
            "citizens' democratic engagement; crisis, governance, and "
            "development; democracy and technology; democracy and "
            "climate; democratic backsliding, resilience, and "
            "resistance; and media, political communications, political "
            "psychology, and democracy. Fellows receive a $2,000 stipend "
            "(paid upon completion), 20 hours per semester of research "
            "assistance from CGD's undergraduate research assistants, "
            "access to the DARE (Democratic Attacks and Resistance "
            "Events) datasets, and support disseminating research "
            "through CGD's communications channels. In exchange, "
            "Fellows participate in CGD conferences, seminars, and "
            "workshops; produce two CGD Policy Briefs and two media-"
            "outreach pieces; collaborate on an ongoing CGD research "
            "project; and complete one CGD service activity (e.g. "
            "reviewing working papers or assisting with student "
            "mentoring). Required application materials: a CV, a "
            "two-page cover letter, and a writing sample (academic "
            "article and/or policy brief)."
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
    parser = argparse.ArgumentParser(description="Cornell CGD Non-Resident Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Cornell CGD Non-Resident Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Cornell CGD Non-Resident Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
