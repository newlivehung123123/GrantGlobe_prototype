#!/usr/bin/env python3
"""
Mila AI Policy Fellowship (Quebec, Canada) connector.

Mila (the Quebec AI Institute) runs a six-month AI Policy Fellowship
connecting AI research and policy through a socio-technical approach. Each
year, a new cohort of fellows works with Mila's AI Advisors and AI Policy
Secretariat on a set of annual thematic areas — for the 2026-2027 cohort:
AI/Information Integrity/Democratic Governance, AI/Health and Wellbeing,
AI Sovereignty and Security, Indigenous AI, AI/Education and Workforce
Transformation, and AI/Climate and the Natural World.

The program's source page states: "Applications for the 2026 cohort are
open until April 16, midnight (anywhere on Earth)." That date has already
passed as of this connector's construction. The page confirms the program
runs annually ("each year, a new cohort...") but does not explicitly state
that April 16 is a fixed, recurring annual deadline — this is a sourced
date advanced by one year under this pipeline's standard annual-cycling
convention (cycle_years=1), on the reasonable but not fully confirmed
inference that the cohort cadence implies a roughly similar deadline each
year. This should be re-verified against the live page once the 2027 cycle
is announced.

Source: https://mila.quebec/en/ai4humanity/ai-governance-policy-and-inclusion/mila-ai-policy-fellowship

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/mila_ai_policy.py [--dry-run]
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

FUNDER = "Mila — Quebec AI Institute"
DOMAIN = "api_mila_ai_policy"
PORTAL_GENERAL = "https://mila.quebec/en/ai4humanity/ai-governance-policy-and-inclusion/mila-ai-policy-fellowship"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Mila AI Policy Fellowship",
        "url":      PORTAL_GENERAL,
        "portal":   PORTAL_GENERAL,
        # Sourced as "April 16, midnight (anywhere on Earth)" for the 2026
        # cohort; advanced by one annual cycle per this pipeline's standard
        # convention since that date has passed (see module docstring caveat).
        "deadline":   datetime.date(2026, 4, 16),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["AI Governance", "AI Policy"],
        "individual": ["Researcher", "Policy Professional"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CA"],  # CHAR(2)[] column — ISO-2 code, not full name
        "desc": (
            "Mila's AI Policy Fellowship bridges AI research and policy "
            "through a socio-technical approach. This six-month, "
            "fully-funded program (15 hours/week, September to February) "
            "brings together experts from AI and other fields to work "
            "with Mila's AI Advisors and AI Policy Secretariat on a set "
            "of annual thematic areas. Open worldwide (not restricted to "
            "Canada); requires a graduate degree (MSc/MA or equivalent), "
            "at least three years of professional or academic experience, "
            "and demonstrated policy experience. Visa support is "
            "available for fellows who need to relocate to Quebec."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "CAD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])
    _s.setdefault("focus_countries", ["CA"])  # CHAR(2)[] column — ISO-2 code, not full name


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
    parser = argparse.ArgumentParser(description="Mila AI Policy Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Mila AI Policy Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Mila AI Policy Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
