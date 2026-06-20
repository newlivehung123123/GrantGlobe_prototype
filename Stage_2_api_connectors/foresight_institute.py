#!/usr/bin/env python3
"""
Foresight Institute connector — AI for Science & Safety Nodes.

Foresight Institute is a non-profit that funds and facilitates research into
beneficial uses of frontier technologies, including AI for scientific
discovery and AI safety. Its "AI for Science & Safety Nodes" programme
provides grants, compute credits, and physical hub space (San Francisco and
Berlin) to researchers, teams, non-profits, and for-profit ventures working
at the intersection of AI capability, science acceleration, and AI safety.

Unlike most academic fellowships, this programme is explicitly open to
individuals without institutional affiliation, informal teams, and for-profit
companies, not just universities or registered non-profits.

Deadline pattern — quarterly, recurring:
  Applications are reviewed on a rolling basis with funding decisions tied to
  the end of each calendar quarter (Mar 31 / Jun 30 / Sep 30 / Dec 31). This
  connector computes the next quarter-end deadline dynamically from today's
  date each time it runs, rather than hard-coding a single future date — so
  it remains correct indefinitely without code changes (no _advance_deadline
  cycle-years logic is needed, unlike the annual/biennial HHMI pattern).
  The status is "Open" throughout each quarter, since the call for proposals
  is continuously open with no interim closed period.

Source: https://foresight.org/grants/grants-ai-for-science-safety/
Portal: https://foresight.org/grants/grants-ai-for-science-safety/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/foresight_institute.py [--dry-run]
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

FUNDER = "Foresight Institute"
DOMAIN = "api_foresight_institute"
BASE   = "https://foresight.org/grants/grants-ai-for-science-safety/"
PORTAL = "https://foresight.org/grants/grants-ai-for-science-safety/"

DESC = (
    "Foresight Institute's AI for Science & Safety Nodes programme provides "
    "grants of approximately $10,000 to $100,000, compute credits, and "
    "physical hub space in San Francisco and Berlin to researchers, teams, "
    "non-profits, and for-profit ventures working at the intersection of AI "
    "capability for scientific discovery and AI safety. The programme is "
    "explicitly open to individuals without institutional affiliation, "
    "informal teams, and for-profit companies, in addition to universities "
    "and registered non-profits. Applications are reviewed on a rolling "
    "basis, with funding decisions made at the close of each calendar "
    "quarter; the next decision point is the end of the current quarter. "
    "Apply via the online form linked from the programme page."
)

SCHEMES: list[dict] = [
    {
        "title":   "Foresight Institute AI for Science & Safety Nodes",
        "url":     BASE,
        "portal":  PORTAL,
        "grant_types": ["Project Grant", "Seed Grant"],
        "individual": [
            "Independent Researcher", "Independent Scholar",
            "Early Career Researcher", "Entrepreneur",
        ],
        "org_types": ["Non-Profit Organisation", "For-Profit Company",
                      "Research Institution", "Startup"],
        "amount_min": 10000,
        "amount_max": 100000,
        "currency": "USD",
        "sectors": [
            "Artificial Intelligence", "AI Safety", "AI Security",
            "Science & Technology", "Research & Innovation",
            "Existential Risk Reduction",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": DESC,
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


def _next_quarter_end(today: datetime.date) -> datetime.date:
    """Return the next calendar-quarter-end date on or after today."""
    quarter_ends = [(3, 31), (6, 30), (9, 30), (12, 31)]
    for month, day in quarter_ends:
        candidate = datetime.date(today.year, month, day)
        if candidate >= today:
            return candidate
    return datetime.date(today.year + 1, 3, 31)


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(scheme: dict, today: datetime.date) -> dict:
    deadline = _next_quarter_end(today)
    days_until = (deadline - today).days
    # Continuously open call throughout each quarter.
    status = "Open"

    deadline_iso = deadline.isoformat()

    return {
        "grant_title":               scheme["title"],
        "funder_name":               FUNDER,
        "source_url":                scheme["url"],
        "application_portal_url":    scheme["portal"],
        "description":               scheme["desc"],
        "application_deadline":      deadline_iso,
        "application_deadline_raw":  "Rolling, quarterly funding decisions "
                                      f"(next: {deadline.strftime('%-d %B %Y')})",
        "grant_opening_date":        today.isoformat(),
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
    parser = argparse.ArgumentParser(description="Foresight Institute connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Foresight Institute — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Foresight Institute: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
