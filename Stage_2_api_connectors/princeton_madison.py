#!/usr/bin/env python3
"""
James Madison Program in American Ideals and Institutions (Princeton
University) — Visiting Fellowship connector.

The James Madison Program, sponsored by Princeton's Department of
Politics, invites both "college and university professors AND other
professionals with established records of scholarship" to apply for
appointments as Visiting Fellows — i.e. the programme is explicitly open
to non-academic professionals, not restricted to university-affiliated
scholars. Fellows hold a nine-month, academic-year appointment in
residence at Princeton (one-semester appointments possible but not
preferred), with access to Firestone Library and University facilities;
all Fellows must hold a doctorate or equivalent degree, and positions are
open regardless of citizenship.

The source page states exactly: "For priority consideration, application
materials must be received by 11:59 p.m. EST on December 5, 2025" (for
appointments beginning September 2026). That date has already passed as
of this connector's construction, so it is advanced by one annual cycle
(cycle_years=1) under this pipeline's standard convention; the page
separately confirms this is a regular annual appointment cycle ("for the
academic year running from September 1, 2026 to June 1, 2027").

Source: https://jmp.princeton.edu/fellowships/visiting-fellows/apply-visiting-fellowship

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/princeton_madison.py [--dry-run]
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

FUNDER = "James Madison Program in American Ideals and Institutions (Princeton University)"
DOMAIN = "api_princeton_madison"
SOURCE_URL = "https://jmp.princeton.edu/fellowships/visiting-fellows/apply-visiting-fellowship"
PORTAL_URL = "https://www.princeton.edu/acad-positions/position/39462"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "James Madison Program Visiting Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: "For priority consideration, application
        # materials must be received by 11:59 p.m. EST on December 5,
        # 2025" (for appointments beginning September 2026).
        "deadline":   datetime.date(2025, 12, 5),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": 130000,
        "sectors":    ["Constitutional Law", "Political Thought", "Political Science"],
        "individual": ["Researcher", "Faculty", "Practitioner"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A nine-month, academic-year Visiting Fellowship at "
            "Princeton's James Madison Program in American Ideals and "
            "Institutions, dedicated to scholarly research in "
            "constitutional law and political thought. The Program "
            "explicitly invites college and university professors AND "
            "other professionals with established records of "
            "scholarship to apply, not restricted to academics; "
            "one-semester appointments are possible but not preferred. "
            "All Fellows must hold a doctorate or equivalent degree, and "
            "positions are open to applicants of any citizenship. "
            "Fellows normally receive a stipend of one-half their "
            "academic-year salary plus a living allowance, up to a "
            "maximum of $130,000; the fellow's home institution is "
            "expected to provide at least half of their academic-year "
            "salary. Fellows spend the appointment in residence at "
            "Princeton or the local vicinity, with access to Firestone "
            "Library and other University facilities."
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
    parser = argparse.ArgumentParser(description="Princeton James Madison Program connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Princeton James Madison Program — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Princeton James Madison Program: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
