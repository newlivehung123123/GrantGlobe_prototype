#!/usr/bin/env python3
"""
The Sumitomo Foundation (Japan) connector.

The Sumitomo Foundation runs several research grant programmes; this
connector covers its two categories genuinely open to international
researchers:

1. Grant for Japan-Related Research Projects — for researchers of Asian
   (non-Japanese) nationality living outside Japan, to conduct research
   in the social sciences or humanities related to Japan, aiming to
   enhance mutual understanding between Asian countries and Japan.

2. Grant for Environmental Research Projects — supporting interdisciplinary
   research addressing global environmental challenges (climate change,
   biodiversity loss, etc.) across natural sciences, social sciences, and
   humanities, with international collaboration strongly encouraged.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.sumitomo.or.jp/e/
Portal: https://grant.sumitomo.or.jp/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/japan_sumitomo.py [--dry-run]
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

FUNDER = "The Sumitomo Foundation (Japan)"
DOMAIN = "api_japan_sumitomo"
BASE   = "https://www.sumitomo.or.jp/e/"
PORTAL = "https://grant.sumitomo.or.jp/"

SCHEMES: list[dict] = [
    {
        "title":   "Sumitomo Foundation Grant for Japan-Related Research Projects",
        "url":     "https://www.sumitomo.or.jp/e/Jare/japanrela.html",
        "portal":  "https://grant.sumitomo.or.jp/jare/login/en/",
        # FY2025 cycle: application period 1 September - 31 October 2025,
        # 5:00pm Japan time (already closed at authoring time).
        "deadline": datetime.date(2025, 10, 31),
        "open_threshold_days": 60,        # application window opens 1 September
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "JPY",
        "sectors": [
            "Social Sciences", "Humanities", "Area Studies",
            "Japanese Studies",
        ],
        "applicant_countries": [],
        "focus_regions": ["Asia"],
        "focus_countries": ["JP"],
        "desc": (
            "The Sumitomo Foundation's Grant for Japan-Related Research "
            "Projects aims to enhance mutual understanding between Asian "
            "countries and Japan by promoting research projects in the "
            "social sciences or humanities that are related to Japan. "
            "Eligible applicants must be researchers of Asian "
            "(non-Japanese) nationality living outside Japan, applying "
            "either individually or as part of a group; the awarded "
            "researcher must personally conduct the proposed research. "
            "The grant budget totals approximately ¥50 million per "
            "fiscal year, with around 70 projects selected, for a "
            "one-year grant period (extendable to a maximum of two "
            "years in unavoidable circumstances). Applications may be "
            "submitted in English or Japanese, comprising an application "
            "form and a free-form letter of recommendation from an "
            "academic referee, both submitted online. The FY2025 "
            "application period ran 1 September to 31 October 2025, "
            "5:00pm Japan time; subsequent cycles follow a similar "
            "annual schedule. Full guidelines are published at "
            "https://www.sumitomo.or.jp/e/Jare/japanrela.html."
        ),
    },
    {
        "title":   "Sumitomo Foundation Grant for Environmental Research Projects",
        "url":     "https://www.sumitomo.or.jp/e/other.htm",
        "portal":  PORTAL,
        # 2026 cycle deadline: 30 June 2026.
        "deadline": datetime.date(2026, 6, 30),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": 10000000,
        "currency": "JPY",
        "sectors": [
            "Environmental Science", "Climate Change", "Biodiversity",
            "Natural Sciences", "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["JP"],
        "desc": (
            "The Sumitomo Foundation's Grant for Environmental Research "
            "Projects supports interdisciplinary research addressing "
            "global environmental challenges such as climate change and "
            "biodiversity loss, spanning the natural sciences, social "
            "sciences, and humanities. International collaboration is "
            "strongly encouraged. Grants provide up to ¥5 million for "
            "General Research and up to ¥10 million for Special Subject "
            "Research. The 2026 cycle's application deadline is 30 June "
            "2026; subsequent cycles follow a similar annual schedule. "
            "Applications are submitted via The Sumitomo Foundation's "
            "online grant portal at https://grant.sumitomo.or.jp/; full "
            "programme details are published at "
            "https://www.sumitomo.or.jp/e/other.htm."
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
    parser = argparse.ArgumentParser(description="Sumitomo Foundation connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Sumitomo Foundation — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Sumitomo Foundation: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
