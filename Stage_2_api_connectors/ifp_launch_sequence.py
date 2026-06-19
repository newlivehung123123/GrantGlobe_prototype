#!/usr/bin/env python3
"""
Institute for Progress (IFP) — Request for Proposals: The Launch Sequence.

The Launch Sequence is IFP's open call for ideas, strategies, and reform
proposals on accelerating progress in science, technology, and innovation
policy (including AI policy). It is structured as an ongoing bounty/
honorarium scheme rather than a traditional academic grant: published
proposals receive a $10,000 honorarium, and successful referrals or
"scouted" ideas earn $1,000 bounties. The call is explicitly open to
non-institutional contributors — strategists, researchers, and domain
experts are invited to apply regardless of institutional affiliation.

Deadline pattern — rolling, no fixed deadline. A far-future sentinel date is
used (per the LTFF/Emergent Ventures convention elsewhere in this codebase)
so the record always shows as "Open".

Source: https://ifp.org/rfp-launch/
Portal: https://ifp.org/rfp-launch/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/ifp_launch_sequence.py [--dry-run]
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

FUNDER = "Institute for Progress (IFP)"
DOMAIN = "api_ifp_launch_sequence"
BASE   = "https://ifp.org/rfp-launch/"
PORTAL = "https://ifp.org/rfp-launch/"

DESC = (
    "The Launch Sequence is the Institute for Progress's open request for "
    "proposals on accelerating progress in science, technology, and "
    "innovation policy, including AI policy and governance. Rather than a "
    "traditional academic grant, it operates as an ongoing honorarium and "
    "bounty scheme: authors of published proposals receive a $10,000 "
    "honorarium, and individuals who refer or scout a successful idea earn "
    "a $1,000 bounty. The call is explicitly open to non-institutional "
    "contributors — strategists, researchers, and domain experts are "
    "invited to submit regardless of institutional affiliation. "
    "Applications and proposal submissions are accepted on a rolling basis "
    "with no fixed deadline. Apply via the form linked from the programme "
    "page."
)

SCHEMES: list[dict] = [
    {
        "title":   "IFP Request for Proposals: The Launch Sequence",
        "url":     BASE,
        "portal":  PORTAL,
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": ["Honorarium", "Bounty", "Policy Fellowship"],
        "individual": [
            "Independent Researcher", "Independent Scholar",
            "Policy Analyst", "Early Career Researcher",
            "Mid-Career Researcher", "Senior Researcher",
        ],
        "org_types": ["Think Tank", "Non-Profit Organisation"],
        "amount_min": 1000,
        "amount_max": 10000,
        "currency": "USD",
        "sectors": [
            "AI Governance", "AI Policy", "Science & Technology Policy",
            "Innovation Policy", "Public Policy",
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
        "application_deadline_raw":  "Rolling (no fixed deadline)",
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
    parser = argparse.ArgumentParser(description="IFP Launch Sequence connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  IFP Launch Sequence — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  IFP Launch Sequence: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
