#!/usr/bin/env python3
"""
Vista Institute for AI Policy connector.

Vista Institute for AI Policy (fiscally sponsored by Rethink Priorities)
primarily selects fellows through its own structured courses and AI Law and
Policy Workshop, but its site also explicitly invites prospective applicants
to reach out directly by email if they have a project idea seeking funding
or mentorship support, outside of the structured programme cycles. This is
a genuine, if limited and passive, funding pathway rather than a fully
structured open call — applicants should expect a more informal,
relationship-driven process than a standard RFP.

Listed here with hedged framing reflecting this limited-capacity, "reach out
directly" pattern (consistent with similar listings elsewhere in this
codebase, e.g. Macroscopic Ventures).

Deadline pattern — rolling, no fixed deadline.

Source: https://www.vista-institute.org/
Portal: https://www.vista-institute.org/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/vista_institute.py [--dry-run]
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

FUNDER = "Vista Institute for AI Policy"
DOMAIN = "api_vista_institute"
BASE   = "https://www.vista-institute.org/"
PORTAL = "https://www.vista-institute.org/"

DESC = (
    "Vista Institute for AI Policy, fiscally sponsored by Rethink "
    "Priorities, primarily selects fellows through its own structured "
    "courses and AI Law and Policy Workshop. Outside of these structured "
    "programme cycles, the Institute explicitly invites prospective "
    "applicants with a project idea seeking funding or mentorship support "
    "to reach out directly by email. This is a genuine but limited and "
    "passive funding pathway rather than a fully structured open call: "
    "capacity for unsolicited project support is constrained, and "
    "applicants should expect a more informal, relationship-driven process "
    "than a standard request for proposals. The Institute's focus areas "
    "concern AI governance, AI policy, and AI law. Contact and programme "
    "details are available on the Institute's website."
)

SCHEMES: list[dict] = [
    {
        "title":   "Vista Institute for AI Policy — Project Support & Mentorship",
        "url":     BASE,
        "portal":  PORTAL,
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": ["Mentorship", "Project Grant"],
        "individual": [
            "Independent Researcher", "Early Career Researcher",
            "Policy Analyst",
        ],
        "org_types": ["Non-Profit Organisation"],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "AI Governance", "AI Policy", "Public Policy",
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


def _advance_deadline(
    est: datetime.date,
    cycle_years: int,
    today: datetime.date,
) -> datetime.date:
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
        "application_deadline_raw":  "Rolling (no fixed deadline; limited capacity)",
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
    parser = argparse.ArgumentParser(description="Vista Institute connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Vista Institute for AI Policy — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Vista Institute: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
