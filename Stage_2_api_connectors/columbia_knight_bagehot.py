#!/usr/bin/env python3
"""
Knight-Bagehot Fellowship in Economics and Business Journalism (Columbia
University) connector.

The Knight-Bagehot Fellowship, administered by Columbia Journalism School
since 1975, is a nine-month, mid-career fellowship for working journalists.
The source page states exactly: "The fellowship is open to full-time
editorial employees of newspapers, magazines, wire services, digital
media, television and radio news organizations, as well as to freelance
journalists, from anywhere in the world. Applicants must have at least
four years of business/economics/finance journalism experience and have
received a bachelor's degree (or equivalent) from an accredited
university." This is an explicitly non-academic, working-professional
fellowship — only a bachelor's degree is required, with no PhD or
university affiliation of any kind, mirroring the same eligibility
profile as MIT's Knight Science Journalism Fellowship already in this
pipeline.

The most recently sourced annual deadline was "Saturday, January 31,
2026, at 11:59 pm Eastern Standard Time" for the Class of 2026-2027
(confirmed by the program's own April 23, 2026 announcement of that
incoming cohort). That date has already passed as of this connector's
construction, so it is advanced by one annual cycle (cycle_years=1) under
this pipeline's standard convention; the fellowship is confirmed to run
annually ("We accept up to 10 fellows each year").

Source: https://journalism.columbia.edu/kb-apply
Overview: https://journalism.columbia.edu/knight-bagehot

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/columbia_knight_bagehot.py [--dry-run]
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

FUNDER = "Knight-Bagehot Fellowship in Economics and Business Journalism (Columbia University)"
DOMAIN = "api_columbia_knight_bagehot"
SOURCE_URL = "https://journalism.columbia.edu/kb-apply"
PORTAL_URL = "https://journalism.columbia.edu/kb-apply"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Knight-Bagehot Fellowship in Economics and Business Journalism",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: "The deadline to apply is Saturday, January
        # 31, 2026, at 11:59 pm Eastern Standard Time" (Class of
        # 2026-2027). That date had already passed at construction.
        "deadline":   datetime.date(2026, 1, 31),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        # Sourced: "$7,800 a month" living stipend, for a "nine-month
        # program" (per the program's own Class announcement), i.e.
        # 7,800 x 9 = 70,200; full tuition and health insurance are
        # provided separately and are not quantified on the source page,
        # so are not folded into this figure.
        "amount_max": 70200,
        "sectors":    ["Business Journalism", "Economics Journalism", "Financial Journalism"],
        "individual": ["Journalist", "Practitioner"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A nine-month, mid-career fellowship at Columbia Journalism "
            "School (with most coursework taken at Columbia Business "
            "School) for up to 10 working journalists per year, "
            "offering core MBA classes (corporate finance, accounting, "
            "economics), high-level journalism coursework, and weekly "
            "off-the-record seminars and dinners with media and "
            "business executives. The program states exactly: 'The "
            "fellowship is open to full-time editorial employees of "
            "newspapers, magazines, wire services, digital media, "
            "television and radio news organizations, as well as to "
            "freelance journalists, from anywhere in the world. "
            "Applicants must have at least four years of "
            "business/economics/finance journalism experience and have "
            "received a bachelor's degree (or equivalent) from an "
            "accredited university' — an explicitly non-academic, "
            "working-professional fellowship with no PhD or university "
            "affiliation required. While a majority of fellows "
            "typically come from the U.S., candidates from all parts of "
            "the world are sought. Fellows receive full tuition, health "
            "insurance, and a stipend of $7,800 a month; subsidized "
            "Columbia housing is also available. Fellows are prohibited "
            "from working or freelancing during the fellowship year and "
            "must relocate to New York City."
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
    parser = argparse.ArgumentParser(description="Columbia Knight-Bagehot Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Columbia Knight-Bagehot Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Columbia Knight-Bagehot Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
