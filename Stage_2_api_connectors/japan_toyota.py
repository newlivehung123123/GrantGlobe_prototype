#!/usr/bin/env python3
"""
The Toyota Foundation (Japan) — International Grant Program connector.

The Toyota Foundation's International Grant Program supports projects
that deepen mutual understanding and knowledge-sharing among people in
East Asia, Southeast Asia, and South Asia who are working on shared
regional issues. Project teams must be diverse and based across multiple
target countries in the region, comprising practitioners, researchers,
creators, policymakers, and journalists — not restricted to Japan-based
applicants or to academic researchers alone.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.toyotafound.or.jp/english/grant/international/
Portal: https://www.toyotafound.or.jp/english/grant/international/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/japan_toyota.py [--dry-run]
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

FUNDER = "The Toyota Foundation (Japan) — International Grant Program"
DOMAIN = "api_japan_toyota"
BASE   = "https://www.toyotafound.or.jp/english/grant/international/"
PORTAL = BASE

SCHEMES: list[dict] = [
    {
        "title":   "Toyota Foundation International Grant Program",
        "url":     BASE,
        "portal":  PORTAL,
        # 2026 cycle: application window 1 April - 30 May 2026, 11:59pm
        # Japan Standard Time (already closed at authoring time).
        "deadline": datetime.date(2026, 5, 30),
        "open_threshold_days": 60,        # application window opens 1 April
        "cycle_years": 1,
        "grant_types": ["Project Grant"],
        "individual": [
            "Senior Researcher", "Early Career Researcher",
            "Independent Researcher",
        ],
        "org_types": ["Non-Profit Organisation"],
        "amount_min": None,
        "amount_max": 10000000,
        "currency": "JPY",
        "sectors": [
            "Area Studies", "Social Sciences", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["East Asia", "Southeast Asia", "South Asia"],
        "focus_countries": [],
        "desc": (
            "The Toyota Foundation's International Grant Program "
            "supports projects that deepen mutual understanding and "
            "knowledge-sharing among people on the ground in East Asia, "
            "Southeast Asia, and South Asia who are finding solutions to "
            "shared regional issues. Eligible projects are led by "
            "diverse teams based across multiple target countries in "
            "the region, comprising practitioners, researchers, "
            "creators, policymakers, and journalists — the programme is "
            "not restricted to Japan-based applicants or to academic "
            "researchers alone. Grants provide up to ¥5,000,000 for "
            "one-year projects and up to ¥10,000,000 for two-year "
            "projects. Prospective applicants may first consult with "
            "the programme officer by submitting a concept note via "
            "email before preparing a full proposal. The 2026 cycle's "
            "application window ran from 1 April to 30 May 2026, "
            "11:59pm Japan Standard Time, with formal funding decisions "
            "made by the Toyota Foundation's Board of Directors in late "
            "September 2026; subsequent cycles follow a similar annual "
            "schedule. Applications are submitted online via the "
            "Toyota Foundation's grant portal, with full guidelines at "
            "https://www.toyotafound.or.jp/english/grant/international/."
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
        "application_deadline_raw":  scheme.get(
            "deadline_raw", f"{deadline.day} {deadline.strftime('%B %Y')}"
        ),
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
    cur.execute(
        "SELECT id FROM grants WHERE source_url = %s AND grant_title = %s",
        (db_rec["source_url"], db_rec["grant_title"]),
    )
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
    parser = argparse.ArgumentParser(description="Toyota Foundation connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Toyota Foundation — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Toyota Foundation: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
