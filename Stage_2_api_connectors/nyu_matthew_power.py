#!/usr/bin/env python3
"""
Matthew Power Literary Reporting Award (NYU Arthur L. Carter Journalism
Institute) connector.

The Matthew Power Literary Reporting Award is a $15,000 grant, offered
annually since 2015 (the 2026 cycle was its 12th edition, won by Danielle
Mackey for a project on U.S.-El Salvador relations), to support the
reporting and writing of a single work of longform nonfiction journalism
or a substantial audio piece (over 20 minutes). It is explicitly open to
journalists worldwide, independent of any academic or institutional
affiliation: the program's own FAQ states "I am not a U.S. citizen. Am I
eligible to apply? ... Yes, you are. There are no citizenship nor
residency requirements," and confirms freelancers, full-time staff
journalists, and co-writing teams may all apply. The only disqualifying
affiliation is with NYU itself: "current NYU students are ineligible, and
NYU graduates (with whatever degree) must wait until two years after
graduation to apply" — i.e. this is a program deliberately designed for
journalists with no current academic affiliation of any kind, mirroring
the eligibility profile of the other working-journalist fellowships
already in this pipeline (MIT KSJ, Columbia Knight-Bagehot), but
structured as a single project grant rather than a residency.

The most recently confirmed annual deadline was "February 22nd, 2026" for
the 2026 award (winner announced in April/May 2026), which has already
passed as of this connector's construction. The official program page
(modified May 2026) confirms the program continues on its regular annual
cycle: "Applications for the 2027 award open in November" — consistent
with the prior cycle's November-opening, February-deadline pattern. The
deadline is therefore advanced by one annual cycle (cycle_years=1) under
this pipeline's standard convention.

Source: https://journalism.nyu.edu/about-us/awards-and-fellowships/matthew-power-literary-reporting-award/
FAQs: https://journalism.nyu.edu/about-us/awards-and-fellowships/matthew-power-literary-reporting-award/faqs/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/nyu_matthew_power.py [--dry-run]
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

FUNDER = "Matthew Power Literary Reporting Award (Arthur L. Carter Journalism Institute, New York University)"
DOMAIN = "api_nyu_matthew_power"
SOURCE_URL = "https://journalism.nyu.edu/about-us/awards-and-fellowships/matthew-power-literary-reporting-award/"
PORTAL_URL = "https://nyujournalism.submittable.com/submit/341429/2026-matthew-power-literary-reporting-award"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Matthew Power Literary Reporting Award",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "proposal deadline is February 22nd, 2026" for the
        # 2026 award (12th edition; winner announced ~April 2026). That
        # date had already passed at construction.
        "deadline":   datetime.date(2026, 2, 22),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": 15000,
        "amount_max": 15000,
        "sectors":    ["Literary Journalism", "Nonfiction Reportage", "Long-form Journalism"],
        "individual": ["Journalist", "Practitioner"],
        "grant_types": ["Grant"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A grant of $15,000, offered annually since 2015 in memory of "
            "journalist Matthew Power, to support the reporting and "
            "writing of a single work of longform nonfiction journalism "
            "(or a substantial audio piece running over 20 minutes) on a "
            "story that 'uncovers truths about the human condition.' The "
            "award is judged by a panel of NYU journalism professors, "
            "outside writers, and editors, with finalists interviewed "
            "online; it does not fund armed-conflict reporting or "
            "primarily investigatory projects, and money may be used for "
            "travel and other reporting expenses. Eligibility is "
            "explicitly independent of academic or institutional "
            "affiliation: per the program's own FAQ, 'I am not a U.S. "
            "citizen. Am I eligible to apply? ... Yes, you are. There "
            "are no citizenship nor residency requirements,' and "
            "freelancers, full-time staff journalists, and co-writing "
            "teams may all apply, with no requirement to relocate to "
            "New York. The sole disqualifying affiliation is with NYU "
            "itself: 'current NYU students are ineligible, and NYU "
            "graduates (with whatever degree) must wait until two years "
            "after graduation to apply.' Applicants should be "
            "early-career in the sense of not yet being 'established and "
            "well-known' as longform nonfiction journalists; the winner "
            "normally receives visiting scholar privileges at NYU, "
            "including library access. Applicants may apply to either "
            "this award or NYU Journalism's separate Reporting Award in "
            "a given year, but not both."
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
    parser = argparse.ArgumentParser(description="NYU Matthew Power Literary Reporting Award connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  NYU Matthew Power Literary Reporting Award — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  NYU Matthew Power Literary Reporting Award: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
