#!/usr/bin/env python3
"""
Turkey — TÜBİTAK (The Scientific and Technological Research Council of
Türkiye) connector — 2232 International Fellowship Programmes.

TÜBİTAK's 2232 programmes are designed to bring outstanding researchers
of any nationality (including Turkish citizens based abroad) to work at
a host institution in Türkiye, fully funded by TÜBİTAK (not a bilateral
matching-fund scheme). This connector covers both tiers:

1. 2232-A International Fellowship for Outstanding Researchers — for
   highly experienced researchers, offering substantial multi-year
   project funding.

2. 2232-B International Fellowship for Early-Stage Researchers — for
   researchers within a few years of their PhD.

(TÜBİTAK separately runs 2216 — a Research Fellowship Programme for
International Researchers — and several joint postgraduate/postdoctoral
programmes with TWAS and WAITRO, but these do not have a clearly
verifiable recurring deadline at the time of writing and are not
included here. 2219 is restricted to Turkish citizens going abroad and
is out of scope for this project's international-access orientation.)

Deadline pattern — TÜBİTAK runs calls roughly twice a year (a
spring/early-year call and a autumn call); this connector anchors to
the most recently confirmed call (closed 24 November 2025) and advances
annually (cyclical-advance, as in hhmi.py/fli.py). The exact call
calendar should be re-verified periodically, since TÜBİTAK does not
publish multi-year-ahead dates.

Source: https://tubitak.gov.tr/en/scholarships/postdoctoral/research-scholarship-programs/2232-international-fellowship-outstanding-researchers
Portal: https://e-bideb.tubitak.gov.tr/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/turkey_tubitak.py [--dry-run]
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

FUNDER = "TÜBİTAK (The Scientific and Technological Research Council of Türkiye)"
DOMAIN = "api_turkey_tubitak"
PORTAL = "https://e-bideb.tubitak.gov.tr/"

SCHEMES: list[dict] = [
    {
        "title":   "TÜBİTAK 2232-A International Fellowship for Outstanding Researchers",
        "url":     "https://tubitak.gov.tr/en/scholarships/postdoctoral/research-scholarship-programs/2232-international-fellowship-outstanding-researchers",
        "portal":  PORTAL,
        # Most recently confirmed call closed 24 November 2025.
        "deadline": datetime.date(2025, 11, 24),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Senior Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "TRY",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Engineering", "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["TR"],
        "desc": (
            "TÜBİTAK 2232-A International Fellowship for Outstanding "
            "Researchers brings highly experienced researchers of any "
            "nationality — including Turkish citizens based abroad — "
            "to carry out research at a host institution in Türkiye, "
            "with substantial multi-year project funding fully covered "
            "by TÜBİTAK. TÜBİTAK typically runs this call roughly twice "
            "a year (a spring/early-year call and an autumn call); the "
            "most recently confirmed call closed 24 November 2025. "
            "Subsequent cycles follow a similar annual schedule, though "
            "exact call dates should be re-verified periodically. Full "
            "guidelines are published at https://tubitak.gov.tr/en/"
            "scholarships/postdoctoral/research-scholarship-programs/"
            "2232-international-fellowship-outstanding-researchers."
        ),
    },
    {
        "title":   "TÜBİTAK 2232-B International Fellowship for Early-Stage Researchers",
        "url":     "https://tubitak.gov.tr/en/scholarships/postdoctoral/research-scholarship-programs/2232-b-international-fellowship-early-stage-researchers",
        "portal":  PORTAL,
        # Most recently confirmed call closed 24 November 2025.
        "deadline": datetime.date(2025, 11, 24),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "TRY",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Engineering", "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["TR"],
        "desc": (
            "TÜBİTAK 2232-B International Fellowship for Early-Stage "
            "Researchers brings researchers of any nationality within "
            "a few years of their PhD to carry out research at a host "
            "institution in Türkiye, fully funded by TÜBİTAK. TÜBİTAK "
            "typically runs this call roughly twice a year (a "
            "spring/early-year call and an autumn call); the most "
            "recently confirmed call closed 24 November 2025. "
            "Subsequent cycles follow a similar annual schedule, though "
            "exact call dates should be re-verified periodically. Full "
            "guidelines are published at https://tubitak.gov.tr/en/"
            "scholarships/postdoctoral/research-scholarship-programs/"
            "2232-b-international-fellowship-early-stage-researchers."
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
    parser = argparse.ArgumentParser(description="Turkey TÜBİTAK connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Turkey TÜBİTAK — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Turkey TÜBİTAK: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
