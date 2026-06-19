#!/usr/bin/env python3
"""
Effective Altruism Infrastructure Fund (EAIF) connector.

EAIF is one of the EA Funds (administered by the Effective Ventures
Foundation), dedicated to building and strengthening the infrastructure of
the effective altruism community and adjacent cause areas — including talent
pipelines, knowledge access, and capital allocation for high-impact projects,
several of which concern AI safety and AI governance field-building.

The fund accepts applications on a rolling basis throughout the year with
no fixed submission deadline, following the same structural pattern as the
Long-Term Future Fund (see ltff.py) and Emergent Ventures elsewhere in this
codebase. The sentinel deadline is set far in the future (2035) so it always
shows as Open.

Source: https://funds.effectivealtruism.org/funds/ea-community
Portal: https://av20jp3z.paperform.co/?fund=EA%20Infrastructure%20Fund

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/eaif.py [--dry-run]
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

FUNDER = "Effective Altruism Infrastructure Fund (EA Funds)"
DOMAIN = "api_eaif"
BASE   = "https://funds.effectivealtruism.org/funds/ea-community"
PORTAL = "https://av20jp3z.paperform.co/?fund=EA%20Infrastructure%20Fund"

DESC = (
    "The Effective Altruism Infrastructure Fund (EAIF) is one of the EA "
    "Funds, managed by Effective Ventures Foundation, dedicated to "
    "building and strengthening the infrastructure of the effective "
    "altruism community and adjacent cause areas. It funds projects that "
    "improve talent pipelines, knowledge access, and capital allocation for "
    "high-impact work, including community-building, research support "
    "organisations, and field-building efforts relevant to AI safety and AI "
    "governance. Past grantees have included individual organisers, "
    "early-stage organisations, and established non-profits; both "
    "individuals and organisations are eligible to apply. Applications are "
    "accepted on a rolling basis throughout the year via an online form; "
    "there is no fixed deadline. Grant decisions are made periodically by a "
    "panel of fund managers as applications accumulate. Apply via the "
    "online form at "
    "https://av20jp3z.paperform.co/?fund=EA%20Infrastructure%20Fund."
)

SCHEMES: list[dict] = [
    {
        "title":   "Effective Altruism Infrastructure Fund",
        "url":     BASE,
        "portal":  PORTAL,
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": ["Project Grant", "Organisational Grant"],
        "individual": [
            "Independent Researcher", "Independent Scholar",
            "Early Career Researcher", "Mid-Career Researcher",
            "Community Organiser",
        ],
        "org_types": ["Non-Profit Organisation", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "AI Governance", "Civic Engagement", "Research & Innovation",
            "Existential Risk Reduction", "Capacity Building",
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
    parser = argparse.ArgumentParser(description="EAIF connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Effective Altruism Infrastructure Fund — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  EAIF: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
