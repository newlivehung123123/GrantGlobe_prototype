#!/usr/bin/env python3
"""
JSPS Invitational Fellowships for Research in Japan connector.

Distinct from jsps_japan.py (which covers JSPS's Postdoctoral Fellowships
for early-career researchers via a live scraper of JSPS's schedule pages),
this connector covers JSPS's Invitational Fellowships — for established
researchers based outside Japan, of any nationality and any research
field, to conduct collaborative research with leading research groups at
Japanese universities and institutions for single visits of 14 days to 10
months (Short-term) or longer (Long-term).

JSPS runs two recruitment rounds per fiscal year: a 1st recruitment
(covering both Long-term and Short-term applications) and a 2nd
recruitment (Short-term only). This connector uses the static
sentinel/annual-cycle pattern (as in hhmi.py/fli.py) rather than a live
scraper, since the schedule page's table column layout differs from the
one jsps_japan.py's parser expects.

Source: https://www.jsps.go.jp/english/e-inv/application/index.html
Portal: https://www.jsps.go.jp/english/e-inv/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/jsps_invitational.py [--dry-run]
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

FUNDER = "Japan Society for the Promotion of Science (JSPS) — Invitational Fellowships"
DOMAIN = "api_jsps_invitational"
BASE   = "https://www.jsps.go.jp/english/e-inv/application/index.html"
PORTAL = "https://www.jsps.go.jp/english/e-inv/"

DESC = (
    "JSPS Invitational Fellowships for Research in Japan provide "
    "opportunities for established researchers based outside Japan, of "
    "any nationality and in any research field, to conduct collaborative "
    "research with leading research groups at Japanese universities and "
    "research institutions. Short-term fellowships cover single visits "
    "of 14 days to 10 months; Long-term fellowships cover longer stays. "
    "Eligible applicants are researchers with an excellent record of "
    "research achievements; applications are submitted by the Japanese "
    "host institution to JSPS on the candidate's behalf. JSPS runs two "
    "recruitment rounds per fiscal year: a 1st recruitment covering both "
    "Long-term and Short-term applications, and a 2nd recruitment "
    "covering Short-term applications only. Full guidelines and the "
    "current fiscal year's application schedule are published at "
    "https://www.jsps.go.jp/english/e-inv/."
)

SCHEMES: list[dict] = [
    {
        "title":   "JSPS Invitational Fellowships for Research in Japan — 1st Recruitment (Long-term & Short-term)",
        "url":     BASE,
        "portal":  PORTAL,
        # FY2027 1st recruitment: application deadline 28 August 2026
        # (host institution to JSPS, by 5pm JST).
        "deadline": datetime.date(2026, 8, 28),
        "open_threshold_days": 60,        # electronic system opens ~2 months prior
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Senior Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "JPY",
        "sectors": ["Science & Technology", "Research & Innovation"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Japan"],
        "desc": DESC,
    },
    {
        "title":   "JSPS Invitational Fellowships for Research in Japan — 2nd Recruitment (Short-term)",
        "url":     BASE,
        "portal":  PORTAL,
        # FY2027 2nd recruitment: application deadline 23 April 2027
        # (host institution to JSPS, by 5pm JST).
        "deadline": datetime.date(2027, 4, 23),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Senior Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "JPY",
        "sectors": ["Science & Technology", "Research & Innovation"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Japan"],
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
    parser = argparse.ArgumentParser(description="JSPS Invitational Fellowships connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  JSPS Invitational Fellowships — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  JSPS Invitational: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
