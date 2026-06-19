#!/usr/bin/env python3
"""
Lewis Walpole Library (Yale University) — Visiting Fellowships and Travel
Grants connector.

The Lewis Walpole Library, Yale's research library for the British world
of the long eighteenth century, funds four-week visiting fellowships and
two-week travel grants for research in its collections. Eligibility is
restricted to "scholars pursuing postdoctoral or advanced research" and
"doctoral candidates at work on a dissertation" — i.e. this scheme is
academic-only (and, for doctoral candidates, only at the dissertation
stage), not explicitly open to non-academic professionals or independent
researchers, unlike the Yale LGBT Studies Research Fellowship built
alongside it in this pipeline.

The source page states exactly: "Applications are accepted beginning June
1, and the deadline for submitting applications is November 1" (the most
recently published instance of this deadline was 1 November 2025, for the
2026-27 fellowship year, which the page separately confirms "has
passed"). That sourced date is therefore advanced by one annual cycle
(cycle_years=1) under this pipeline's standard convention to project the
next (1 November 2026) round.

Source: https://walpole.library.yale.edu/fellowships/visiting-fellowships-and-travel-grants

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/lewis_walpole.py [--dry-run]
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

FUNDER = "Lewis Walpole Library (Yale University)"
DOMAIN = "api_lewis_walpole"
SOURCE_URL = "https://walpole.library.yale.edu/fellowships/visiting-fellowships-and-travel-grants"
PORTAL_URL = "http://apply.interfolio.com/167887"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Lewis Walpole Library Visiting Fellowship / Travel Grant",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: "Applications are accepted beginning June 1,
        # and the deadline for submitting applications is November 1";
        # most recent instance (1 November 2025, for the 2026-27
        # fellowship year) had already passed at construction.
        "deadline":   datetime.date(2025, 11, 1),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["British History", "Eighteenth-Century Studies", "Humanities"],
        "individual": ["Researcher", "Post-doctoral Scholar", "Doctoral Student"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "Four-week visiting fellowships and two-week travel grants "
            "for research in the Lewis Walpole Library's collections on "
            "the British world of the long eighteenth century, held in "
            "residence at the Library's Farmington, Connecticut campus "
            "(fellows also gain access to Yale's Sterling Memorial "
            "Library, Beinecke Rare Book and Manuscript Library, and "
            "Yale Center for British Art). Eligibility is restricted to "
            "scholars pursuing postdoctoral or advanced research, or "
            "doctoral candidates at work on a dissertation — academic-"
            "only, not explicitly open to non-academic professionals or "
            "independent researchers. Funded benefits include round-"
            "trip travel, accommodation in an on-campus eighteenth-"
            "century house, and a per diem living allowance calculated "
            "using US GSA rates for the Hartford, CT area."
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
    parser = argparse.ArgumentParser(description="Lewis Walpole Library connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Lewis Walpole Library — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Lewis Walpole Library: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
