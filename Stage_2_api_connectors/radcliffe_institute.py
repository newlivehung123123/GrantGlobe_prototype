#!/usr/bin/env python3
"""
Radcliffe Institute for Advanced Study (Harvard University) — Radcliffe
Fellowship connector.

The Radcliffe Fellowship is Harvard's flagship, university-wide fellowship
for the 2027-2028 program year, open to scholars, scientists, artists, and
public intellectuals — explicitly NOT restricted to academics. It carries
two separate, exact, sourced deadlines depending on discipline cluster:

  - September 10, 2026, 5:00 PM ET — humanities, social sciences, creative
    arts, nonfiction, and journalism.
  - October 1, 2026, 5:00 PM ET — science, engineering, and mathematics.

Eligibility requires a doctorate (or equivalent terminal credential/career
record) received at least four years before the appointment begins (i.e.,
by December 2023 for the 2027-2028 cohort); current degree-program
enrollees and former Radcliffe fellows (1999-present) are ineligible. This
is not a postdoctoral fellowship. Fellows receive a $78,000 stipend plus a
$5,000 project allowance, with relocation/housing/childcare support
available, and must be in residence in the Cambridge/Boston area from
September through May.

Source: https://www.radcliffe.harvard.edu/radcliffe-fellowship/application-information
Application portal: https://radcliffe.secure-platform.com/site/solicitations/login/103017

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/radcliffe_institute.py [--dry-run]
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

FUNDER = "Radcliffe Institute for Advanced Study (Harvard University)"
DOMAIN = "api_radcliffe_institute"
SOURCE_URL = "https://www.radcliffe.harvard.edu/radcliffe-fellowship/application-information"
PORTAL_URL = "https://radcliffe.secure-platform.com/site/solicitations/login/103017"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title": "Radcliffe Fellowship — Humanities, Social Sciences, Creative Arts, Nonfiction & Journalism",
        # Sourced exactly: "September 10, 2026, at 5 PM ET".
        "deadline": datetime.date(2026, 9, 10),
        "sectors": ["Humanities", "Social Sciences", "Creative Arts", "Nonfiction", "Journalism"],
        "desc": (
            "A full-time, year-long Harvard fellowship (residency required "
            "in the Cambridge/Boston area, September through May) for "
            "scholars, writers, and artists in the humanities, social "
            "sciences, creative arts, nonfiction, and journalism, to "
            "pursue an independent project. Applicants must have received "
            "a doctorate or equivalent terminal credential/career record "
            "at least four years prior to appointment; the humanities and "
            "social sciences require a monograph or at least two refereed "
            "articles, while nonfiction/journalism and creative-arts "
            "applicants are assessed against discipline-specific criteria "
            "(e.g., journalists need at least five years of professional "
            "experience). Current degree-program enrollees and former "
            "Radcliffe fellows (1999-present) are ineligible. Provides a "
            "$78,000 stipend plus a $5,000 project expense allowance, with "
            "relocation, housing, and childcare support available."
        ),
    },
    {
        "title": "Radcliffe Fellowship — Science, Engineering & Mathematics",
        # Sourced exactly: "October 1, 2026, at 5 PM ET".
        "deadline": datetime.date(2026, 10, 1),
        "sectors": ["Science", "Engineering", "Mathematics"],
        "desc": (
            "A full-time, year-long Harvard fellowship (residency required "
            "in the Cambridge/Boston area, September through May) for "
            "scientists, engineers, and mathematicians to pursue an "
            "independent project. Applicants must have received a "
            "doctorate or equivalent at least four years prior to "
            "appointment, with at least five refereed articles. Current "
            "degree-program enrollees and former Radcliffe fellows "
            "(1999-present) are ineligible. Provides a $78,000 stipend "
            "plus a $5,000 project expense allowance, with relocation, "
            "housing, and childcare support available."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("url", SOURCE_URL)
    _s.setdefault("portal", PORTAL_URL)
    _s.setdefault("cycle_years", 1)
    _s.setdefault("open_threshold_days", 90)
    _s.setdefault("amount_min", 78000)
    _s.setdefault("amount_max", 83000)
    _s.setdefault("individual", ["Researcher", "Artist", "Writer", "Public Intellectual"])
    _s.setdefault("grant_types", ["Fellowship"])
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
    parser = argparse.ArgumentParser(description="Radcliffe Institute Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Radcliffe Institute — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Radcliffe Institute: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
