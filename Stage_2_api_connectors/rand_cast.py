#!/usr/bin/env python3
"""
RAND CAST (Center for Applied Strategies and Technology) Fellowship connector.

RAND's CAST Fellowship offers a genuinely continuous/rolling application
process with no fixed annual deadline — applications are considered as
they arrive rather than against a fixed cutoff date. As of this scouting
pass (December 2025 source data), CAST is only considering applicants in
AI Security, Technology Policy and Governance, or biosecurity. Eligibility
is limited to US- or UK-based applicants who are eligible for government
security clearance.

This connector uses the same far-future-sentinel convention used elsewhere
in this pipeline for genuinely rolling programs with no fixed deadline
(e.g., FAPESP's standing bilateral mechanisms, fapesp.py), so the scheme
always displays as "Open" rather than carrying a fabricated specific date.

Note: RAND's separate Stanton Nuclear Security Fellows Program was also
scouted but is deliberately NOT included here — its application page only
states a "fall" opening and "selections by February," with no exact
calendar deadline published anywhere found, so it is deferred pending a
sourced exact date rather than built with a fabricated one.

Source: https://www.rand.org/jobs/cast-fellows.html

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/rand_cast.py [--dry-run]
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

FUNDER = "RAND Corporation — CAST Fellowship"
DOMAIN = "api_rand_cast"
PORTAL_GENERAL = "https://www.rand.org/jobs/cast-fellows.html"
ORG_NONE: list[str] = []

# Far-future sentinel for rolling/continuous-flow mechanisms with no fixed
# deadline, so the scheme always evaluates to "Open" — same convention used
# for FAPESP's standing bilateral mechanisms (fapesp.py) elsewhere in this
# pipeline.
ROLLING_SENTINEL = datetime.date(2035, 12, 31)

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "RAND CAST (Center for Applied Strategies and Technology) Fellowship",
        "url":      PORTAL_GENERAL,
        "portal":   PORTAL_GENERAL,
        "deadline":   ROLLING_SENTINEL,
        "cycle_years": 5,
        "open_threshold_days": 3500,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["AI Security", "Technology Policy and Governance", "Biosecurity"],
        "individual": ["Researcher", "Policy Professional"],
        "grant_types": ["Fellowship"],
        "applicant_countries": ["US", "GB"],  # CHAR(2)[] column — ISO-2 codes, not full names
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "The CAST Fellowship is RAND's continuous, rolling-admission "
            "fellowship program for the Center for Applied Strategies and "
            "Technology, considering applications as they arrive rather "
            "than against a fixed annual deadline. As of this scouting "
            "pass, RAND is only considering CAST applicants in AI "
            "Security, Technology Policy and Governance, or biosecurity. "
            "Eligibility is limited to applicants based in the US or UK "
            "who are eligible for government security clearance."
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
    is_rolling = scheme["deadline"] == ROLLING_SENTINEL

    if days_until < 0:
        status = "Closed"
    elif days_until <= thr:
        status = "Open"
    else:
        status = "Forthcoming"

    opening = deadline - datetime.timedelta(days=thr)
    deadline_iso = deadline.isoformat()
    deadline_raw = "Rolling (no fixed deadline)" if is_rolling else deadline.strftime("%d %B %Y")

    return {
        "grant_title":               scheme["title"],
        "funder_name":               FUNDER,
        "source_url":                scheme["url"],
        "application_portal_url":    scheme["portal"],
        "description":               scheme["desc"],
        "application_deadline":      deadline_iso,
        "application_deadline_raw":  deadline_raw,
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
    parser = argparse.ArgumentParser(description="RAND CAST Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  RAND CAST Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  RAND CAST Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
