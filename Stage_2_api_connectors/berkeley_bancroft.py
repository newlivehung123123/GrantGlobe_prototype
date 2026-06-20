#!/usr/bin/env python3
"""
The Bancroft Library (University of California, Berkeley) — Donald
Sidney-Fryer Fellowship connector.

The Bancroft Library's fellowships page lists a distinct "Independent
scholar fellowships" category, separate from its graduate- and
undergraduate-student fellowship categories. The Donald Sidney-Fryer
Fellowship is the sole fellowship listed under that "Independent scholar"
heading, and its eligibility text states — twice, verbatim, on the
official page — "The fellowship is intended to support qualified
researchers regardless of academic degree." This is an explicitly
non-academic-inclusive program: no PhD, university affiliation, or
enrollment status of any kind is required.

(Note: a second Bancroft fellowship, the "Reese" award, was reported by
search summaries as carrying similar "regardless of academic degree"
eligibility language, but the canonical current page's own "Reese"
detail section contains only a list of past winners with no
accompanying eligibility/award-size text block, unlike the parallel
Sidney-Fryer section. Absent a clean, direct-source confirmation of
Reese's current eligibility terms, it is not built as a connector here,
consistent with this pipeline's sourced-only discipline.)

The source page states exactly, repeated under every individual
fellowship's section: "The application deadline for all Bancroft
fellowships and awards is March 2, 2026, by 11:59 p.m." That date has
already passed as of this connector's construction, so it is advanced by
one annual cycle (cycle_years=1) under this pipeline's standard
convention. (A separate, stale mirror page,
https://www.lib.berkeley.edu/libraries/bancroft-library/fellowships-and-awards,
gives an older "first Monday in February" deadline; the canonical,
current page at the URL below — copyright-dated 2026, with "Winners"
entries through the 2023-2024 academic year — supersedes it.)

Source: https://www.lib.berkeley.edu/visit/bancroft/fellowships-awards

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/berkeley_bancroft.py [--dry-run]
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

FUNDER = "The Bancroft Library (University of California, Berkeley)"
DOMAIN = "api_berkeley_bancroft"
SOURCE_URL = "https://www.lib.berkeley.edu/visit/bancroft/fellowships-awards"
PORTAL_URL = "https://forms.gle/GCsJJMLWn2Rmtxvo7"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Donald Sidney-Fryer Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: "The application deadline for all Bancroft
        # fellowships and awards is March 2, 2026, by 11:59 p.m."
        "deadline":   datetime.date(2026, 3, 2),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": 2500,
        "amount_max": 2500,
        "sectors":    ["Literature", "American Literary History", "Cultural History"],
        "individual": ["Researcher", "Independent Scholar"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "Funded by the Aeroflex Foundation, this fellowship supports "
            "scholarly use of primary source materials at The Bancroft "
            "Library related to the works of writers, poets, artists "
            "and their community collectively referred to as the West "
            "Coast Romantics — including Ambrose Bierce, Jack London, "
            "Robinson Jeffers, Mary Austin, George Sterling, Clark "
            "Ashton Smith, Nora May French, Henry Lafler, James Marie "
            "Hopper, Gelett Burgess, Sinclair Lewis, and Xavier "
            "Martinez. The Library states, verbatim and repeated on its "
            "own page: 'The fellowship is intended to support qualified "
            "researchers regardless of academic degree' — i.e. no PhD, "
            "university affiliation, or enrollment status is required; "
            "undocumented applicants are explicitly eligible and no "
            "work authorization is required. The fellowship is offered "
            "in the amount of $2,500 to support a month of study, which "
            "may be used to defray travel, living, or research "
            "expenses; the recipient is expected to be in residence for "
            "whatever term is set by the awarding institution and to "
            "conduct the research project within one year of "
            "notification. Required application materials: a letter of "
            "recommendation submitted directly by the recommender, a "
            "statement of purpose (3,000 words or less for independent "
            "scholars), a list of materials to be consulted with call "
            "numbers/collection names, and a CV or resume."
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
    parser = argparse.ArgumentParser(description="Berkeley Bancroft Library connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Bancroft Library (UC Berkeley) — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Bancroft Library (UC Berkeley): {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
