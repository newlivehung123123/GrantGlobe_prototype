#!/usr/bin/env python3
"""
Alfred P. Sloan Foundation connector.

The Alfred P. Sloan Foundation (~$80M/year in grants) supports fundamental
research and education in science, technology, and economics. Its best-known
programme is the Sloan Research Fellowships: two-year, $75,000 awards given
annually to approximately 125 outstanding early-career researchers in seven
fields — chemistry, computer science, Earth system science, economics,
mathematics, neuroscience, and physics — at colleges and universities in the
United States and Canada.

The Foundation's broader grantmaking (research programmes, higher education,
public understanding of science, New York City) operates on an invitation or
letter-of-inquiry basis with no published open calls.

Grant process (Sloan Research Fellowships):
  Nominations are submitted through SM Apply by a department head or other
  senior researcher. The nomination period opens July 15 each year and closes
  September 15 (letter-writers have until September 22). Independent selection
  committees in each field choose winners, who are announced in mid-February
  of the following year.

Eligibility:
  Candidates must hold a Ph.D. or equivalent in one of the seven fellowship
  fields, be in an untenured tenure-track faculty position with a regular
  teaching obligation at a US or Canadian degree-granting institution, and be
  nominated by a department head or senior researcher. No more than three
  candidates per department per fellowship field may be submitted.

This connector records one entry:
  1. Sloan Research Fellowships — annual nomination cycle; deadline Sep 15.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/sloan_foundation.py [--dry-run]
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

FUNDER  = "Alfred P. Sloan Foundation"
DOMAIN  = "api_sloan"
BASE    = "https://sloan.org"
PORTAL  = f"{BASE}/fellowships/apply-2"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── Sloan Research Fellowships ───────────────────────────────────────
        "title":    "Sloan Research Fellowships",
        "url":      f"{BASE}/fellowships",
        "deadline": datetime.date(2026, 9, 15),     # annual nomination close date
        "open_threshold_days": 62,                   # portal opens Jul 15 (62d before)
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Early Career Faculty"],
        "org_types":  ["University", "Research Institution", "Medical School"],
        "sectors": [
            "Science & Technology", "Life Sciences",
            "Mathematics", "Economics", "Earth & Environment",
            "Research & Innovation",
        ],
        "desc": (
            "The Alfred P. Sloan Foundation's Sloan Research Fellowships are "
            "prestigious two-year, $75,000 awards given annually to approximately "
            "125 outstanding early-career researchers in chemistry, computer "
            "science, Earth system science, economics, mathematics, neuroscience, "
            "and physics at universities and colleges in the United States and "
            "Canada. Since 1955 more than 8,000 researchers have held the "
            "fellowship, including many who subsequently received Nobel Prizes, "
            "Fields Medals, and other top distinctions. "
            "Candidates must hold a Ph.D. or equivalent degree in one of the seven "
            "fellowship fields, hold an untenured tenure-track faculty position "
            "carrying a regular teaching obligation at a US or Canadian "
            "degree-granting institution, and be nominated by a department head or "
            "other senior researcher. No more than three candidates per department "
            "per fellowship field may be nominated. Fellowship funds — paid as a "
            "single lump sum — may be used at the fellow's discretion for any "
            "research-related expense (staffing, professional travel, equipment, lab "
            "costs, or summer salary) but not for institutional indirect costs or "
            "overhead. Fellowship terms begin September 15 of the award year; "
            "winners are announced in mid-February. Nominations for the 2027 Sloan "
            "Research Fellowships open July 15, 2026 and close September 15, 2026 "
            "(letter-writers have until September 22, 2026)."
        ),
    },
]


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
        "application_portal_url":    PORTAL,
        "description":               scheme["desc"],
        "application_deadline":      deadline_iso,
        "application_deadline_raw":  f"{deadline.day} {deadline.strftime('%B %Y')}",
        "grant_opening_date":        opening.isoformat(),
        "current_status":            status,
        "source_language":           "en",
        "funding_amount_min":        75000,
        "funding_amount_max":        75000,
        "currency":                  "USD",
        "thematic_sectors":          scheme["sectors"],
        "grant_types":               scheme["grant_types"],
        "applicant_base_regions":    [],
        "geographic_focus_regions":  ["Global"],
        "applicant_base_countries":  ["US", "CA"],
        "geographic_focus_countries": [],
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
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    db_rec = {k: v for k, v in record.items() if not k.startswith("_")}
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s", (db_rec["source_url"],))
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
    parser = argparse.ArgumentParser(description="Alfred P. Sloan Foundation connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Sloan Foundation — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Sloan: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
