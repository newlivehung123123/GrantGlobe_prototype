#!/usr/bin/env python3
"""
United Nations University (UNU) connector.

UNU is a global think tank and postgraduate teaching organisation
comprising multiple institutes worldwide. This connector covers genuine
recurring fellowship programmes (excluding UNU-WIDER's many one-off
topic-specific "Request for Research Proposals" calls and job vacancies,
which are not modelled here):

1. UNU-WIDER Visiting PhD Fellowship — gives registered doctoral students
   the opportunity to use UNU-WIDER's resources and facilities (Helsinki,
   Finland) for PhD dissertation research on developing economies, for a
   typical 3-month visit. Two recruitment rounds per year.

2. JSPS-UNU Postdoctoral Fellowship Programme — jointly organised by UNU
   (acting as nominating authority via UNU-IAS Tokyo) and the Japan
   Society for the Promotion of Science (JSPS), providing young
   researchers with the opportunity to conduct advanced sustainability
   research under a host researcher at a Japanese university or
   institution, in cooperation with UNU-IAS. Open to citizens of any
   country with diplomatic relations with Japan (Japanese nationals and
   permanent residents are not eligible).

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py);
UNU-WIDER's fellowship has two rounds per year.

Source: https://unu.edu/
Portal: https://www.wider.unu.edu/phdfellows (WIDER) / https://unu.edu/ias/postdoctoral-fellowships (IAS)

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/un_unu.py [--dry-run]
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

FUNDER = "United Nations University (UNU)"
DOMAIN = "api_un_unu"

SCHEMES: list[dict] = [
    {
        "title":   "UNU-WIDER Visiting PhD Fellowship — Round 1",
        "url":     "https://www.wider.unu.edu/phdfellows",
        "portal":  "https://www.wider.unu.edu/opportunity/visiting-phd-fellowship",
        # Round 1: deadline 31 March each year, 23:59 UTC+3.
        "deadline": datetime.date(2026, 3, 31),
        "open_threshold_days": 30,
        "cycle_years": 1,
        "grant_types": ["Visiting PhD Fellowship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "EUR",
        "sectors": [
            "Economics", "Development Studies", "Social Sciences",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": (
            "The UNU-WIDER Visiting PhD Fellowship gives registered "
            "doctoral students the opportunity to use the resources and "
            "facilities of the United Nations University World "
            "Institute for Development Economics Research (UNU-WIDER), "
            "in Helsinki, Finland, for their PhD dissertation or thesis "
            "research on developing economies, and to collaborate with "
            "UNU-WIDER researchers on topics of mutual interest. "
            "Visiting PhD fellows typically spend three consecutive "
            "months at UNU-WIDER before returning to their home "
            "institution, during which they prepare one or more "
            "research papers and present a seminar on their findings. "
            "Applications are accepted in two rounds each year, with "
            "deadlines of 31 March and 30 September, 23:59 UTC+3; this "
            "scheme covers the March round. Full details are published "
            "at https://www.wider.unu.edu/phdfellows."
        ),
    },
    {
        "title":   "UNU-WIDER Visiting PhD Fellowship — Round 2",
        "url":     "https://www.wider.unu.edu/phdfellows",
        "portal":  "https://www.wider.unu.edu/opportunity/visiting-phd-fellowship",
        # Round 2: deadline 30 September each year, 23:59 UTC+3.
        "deadline": datetime.date(2026, 9, 30),
        "open_threshold_days": 30,
        "cycle_years": 1,
        "grant_types": ["Visiting PhD Fellowship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "EUR",
        "sectors": [
            "Economics", "Development Studies", "Social Sciences",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": (
            "The UNU-WIDER Visiting PhD Fellowship gives registered "
            "doctoral students the opportunity to use the resources and "
            "facilities of the United Nations University World "
            "Institute for Development Economics Research (UNU-WIDER), "
            "in Helsinki, Finland, for their PhD dissertation or thesis "
            "research on developing economies, and to collaborate with "
            "UNU-WIDER researchers on topics of mutual interest. "
            "Visiting PhD fellows typically spend three consecutive "
            "months at UNU-WIDER before returning to their home "
            "institution, during which they prepare one or more "
            "research papers and present a seminar on their findings. "
            "Applications are accepted in two rounds each year, with "
            "deadlines of 31 March and 30 September, 23:59 UTC+3; this "
            "scheme covers the September round. Full details are "
            "published at https://www.wider.unu.edu/phdfellows."
        ),
    },
    {
        "title":   "JSPS-UNU Postdoctoral Fellowship Programme",
        "url":     "https://unu.edu/ias/postdoctoral-fellowships",
        "portal":  "https://forms.office.com/r/E0pBp1XMis",
        # Annual application deadline: 31 January, 23:59 JST.
        "deadline": datetime.date(2026, 1, 31),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "JPY",
        "sectors": [
            "Environmental Science", "Climate Change",
            "Public Policy", "Innovation Policy",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["JP"],
        "desc": (
            "The JSPS-UNU Postdoctoral Fellowship Programme is jointly "
            "organised by the United Nations University (acting as "
            "nominating authority via UNU-IAS in Tokyo) and the Japan "
            "Society for the Promotion of Science (JSPS), providing "
            "promising young researchers — especially from the "
            "developing world — with the opportunity to conduct "
            "advanced sustainability research under a host researcher "
            "at a Japanese university or research institution, in "
            "cooperation with UNU-IAS. Since 1996, more than 250 young "
            "researchers (70% from the developing world) have "
            "benefited from the programme. Applicants must hold a "
            "doctoral degree (or be scheduled to receive one by the end "
            "of July 2026) and be citizens of a country with diplomatic "
            "relations with Japan; Japanese nationals and permanent "
            "residents of Japan are not eligible, nor are previous "
            "Standard/Pathway JSPS Postdoctoral Fellows. The fellowship "
            "runs 24 months, with a round-trip airfare, a maintenance "
            "allowance of JPY 362,000 per month, and a settling-in "
            "allowance of JPY 200,000. Research is conducted in one of "
            "four thematic areas: Governance for Climate Change and "
            "Sustainable Development, Biodiversity & Society, Water & "
            "Resource Management, and Innovation & Education. "
            "Applicants must secure a host researcher at an eligible "
            "Japanese institution before applying. The annual "
            "application deadline is 31 January, 23:59 JST; subsequent "
            "cycles follow a similar annual schedule. Full details are "
            "published at https://unu.edu/ias/postdoctoral-fellowships."
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
    parser = argparse.ArgumentParser(description="UNU connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  UNU — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  UNU: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
