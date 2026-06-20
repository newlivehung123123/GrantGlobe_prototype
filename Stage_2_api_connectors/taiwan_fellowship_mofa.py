#!/usr/bin/env python3
"""
Taiwan Fellowship (Ministry of Foreign Affairs, Taiwan) connector.

The Taiwan Fellowship is established by Taiwan's Ministry of Foreign
Affairs (MOFA) specifically to award foreign experts and scholars
interested in research related to Taiwan, cross-strait relations,
mainland China, the Asia-Pacific region, or Chinese studies, enabling them
to conduct advanced research at universities or academic institutions in
Taiwan — directly matching the kind of "funders in Taiwan funding
foreigners to conduct Chinese or Taiwan research" sought for this
codebase's coverage. The fellowship is administered by the Center for
Chinese Studies at Taiwan's National Central Library.

Eligible recipients are foreign professors, associate professors,
assistant professors, postdoctoral researchers, doctoral candidates, or
doctoral programme students at overseas universities, or research fellows
at an equivalent level in academic institutions abroad. Funding is a
monthly stipend: NT$60,000/month for professors, associate professors, and
equivalent-level research fellows; NT$50,000/month for assistant
professors, postdoctoral researchers, doctoral candidates, and doctoral
programme students.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).
The annual application period runs 1 May–30 June each year, for grants
covering January–December of the following year.

Source: https://taiwanfellowship.ncl.edu.tw/eng/about.aspx
Portal: https://taiwanfellowship.ncl.edu.tw/eng/apply01.aspx

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/taiwan_fellowship_mofa.py [--dry-run]
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

FUNDER = "Ministry of Foreign Affairs, Taiwan — Taiwan Fellowship"
DOMAIN = "api_taiwan_fellowship_mofa"
BASE   = "https://taiwanfellowship.ncl.edu.tw/eng/about.aspx"
PORTAL = "https://taiwanfellowship.ncl.edu.tw/eng/apply01.aspx"

SCHEMES: list[dict] = [
    {
        "title":   "Taiwan Fellowship",
        "url":     BASE,
        "portal":  PORTAL,
        # Annual application window: 1 May - 30 June, for grants covering
        # January-December of the following year.
        "deadline": datetime.date(2026, 6, 30),
        "open_threshold_days": 60,        # application window opens 1 May each year
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": [
            "Senior Researcher", "Early Career Researcher",
            "Postdoctoral Researcher", "PhD Student",
        ],
        "org_types": [],
        "amount_min": 50000,
        "amount_max": 60000,
        "currency": "TWD",
        "sectors": [
            "Chinese Studies", "Area Studies", "International Relations",
            "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Taiwan"],
        "desc": (
            "The Taiwan Fellowship is established by Taiwan's Ministry "
            "of Foreign Affairs (MOFA) to award foreign experts and "
            "scholars interested in research related to Taiwan, "
            "cross-strait relations, mainland China, the Asia-Pacific "
            "region, or Chinese studies, enabling them to conduct "
            "advanced research at universities or academic institutions "
            "in Taiwan. Eligible recipients are foreign professors, "
            "associate professors, assistant professors, postdoctoral "
            "researchers, doctoral candidates, or doctoral programme "
            "students at overseas universities, or research fellows at "
            "an equivalent level in academic institutions abroad. "
            "Funding is a monthly stipend: NT$60,000 per month for "
            "professors, associate professors, and equivalent-level "
            "research fellows; NT$50,000 per month for assistant "
            "professors, postdoctoral researchers, doctoral candidates, "
            "doctoral programme students, and other candidates "
            "recommended by ROC (Taiwan) missions abroad. Required "
            "application documents include a valid passport copy, CV, "
            "research proposal, employment letter, proof of salary, and "
            "two recommendation letters, all submitted digitally. The "
            "fellowship is administered by the Center for Chinese "
            "Studies at Taiwan's National Central Library. The annual "
            "application period runs from 1 May to 30 June each year, "
            "for grants covering January-December of the following "
            "year. Full details and the online application are "
            "available at https://taiwanfellowship.ncl.edu.tw/eng/."
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
    parser = argparse.ArgumentParser(description="Taiwan Fellowship (MOFA) connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Taiwan Fellowship (MOFA) — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Taiwan Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
