#!/usr/bin/env python3
"""
Aotearoa New Zealand Tāwhia te Mana Research Fellowships connector.

Run by Royal Society Te Apārangi (New Zealand's national academy) with
MBIE funding, the Tāwhia te Mana Research Fellowships replaced the
Rutherford Discovery Fellowship, Rutherford Foundation Fellowship, and
James Cook Research Fellowship schemes, all of which ended in 2023 (this
connector therefore covers New Zealand's current flagship researcher
fellowship scheme, distinct from marsden_fund.py). Tāwhia te Mana spans
three career-stage tiers sharing the same application window:

1. Mana Tūāpapa Future Leader Fellowship — for early-career researchers
   establishing the foundations of an excellent research career.

2. Mana Tūānuku Research Leader Fellowship — for mid-career researchers
   establishing themselves as experts in their research domain.

3. Mana Tūārangi Distinguished Researcher Fellowship — for researchers
   with expansive, international, and transdisciplinary reputations.

Eligibility requires the applicant to hold a PhD (or have completed all
requirements for one to be conferred) and to be supported by a
New Zealand-based research organisation; no nationality restriction is
stated.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/tawhia-te-mana/
Portal: https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/tawhia-te-mana/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/newzealand_tawhia_te_mana.py [--dry-run]
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

FUNDER = "Royal Society Te Apārangi (New Zealand) — Tāwhia te Mana Research Fellowships"
DOMAIN = "api_newzealand_tawhia_te_mana"
BASE   = "https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/tawhia-te-mana/"
PORTAL = BASE

# 2026 cycle: application portal opens 1 May 2026, closes 9 July 2026,
# 2:00pm NZST (currently open at authoring time).
_DEADLINE = datetime.date(2026, 7, 9)
_OPEN_THRESHOLD_DAYS = 70  # portal opens 1 May each year

SCHEMES: list[dict] = [
    {
        "title":   "Mana Tūāpapa Future Leader Fellowship",
        "url":     BASE + "mana-tuapapa",
        "portal":  PORTAL,
        "deadline": _DEADLINE,
        "open_threshold_days": _OPEN_THRESHOLD_DAYS,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "NZD",
        "sectors": ["Science & Technology", "Research & Innovation"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["NZ"],
        "desc": (
            "The New Zealand Mana Tūāpapa Future Leader Fellowship "
            "supports Aotearoa New Zealand's talented early-career "
            "researchers to establish the foundations of an excellent "
            "research career and develop into future leaders in their "
            "fields. It is one of three tiers within the Tāwhia te Mana "
            "Research Fellowships, run by Royal Society Te Apārangi with "
            "MBIE funding, which replaced the former Rutherford "
            "Discovery, Rutherford Foundation, and James Cook Research "
            "Fellowship schemes (all ended in 2023). Eligible applicants "
            "must hold a PhD (or have completed all requirements for one "
            "to be conferred at the time of application) and be "
            "supported by a New Zealand-based research organisation; no "
            "nationality restriction is stated. The 2026 application "
            "portal opens 1 May 2026 and closes 9 July 2026, 2:00pm "
            "(NZST); subsequent cycles follow a similar annual "
            "schedule. Full terms of reference are published at "
            "https://www.royalsociety.org.nz/what-we-do/funds-and-"
            "opportunities/tawhia-te-mana/."
        ),
    },
    {
        "title":   "Mana Tūānuku Research Leader Fellowship",
        "url":     BASE + "mana-tuanuku",
        "portal":  PORTAL,
        "deadline": _DEADLINE,
        "open_threshold_days": _OPEN_THRESHOLD_DAYS,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Senior Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "NZD",
        "sectors": ["Science & Technology", "Research & Innovation"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["NZ"],
        "desc": (
            "The New Zealand Mana Tūānuku Research Leader Fellowship "
            "supports mid-career researchers in Aotearoa New Zealand to "
            "firmly establish themselves as experts in their research "
            "domain and as emerging leaders within their host "
            "organisations and the wider New Zealand research system. "
            "It is one of three tiers within the Tāwhia te Mana Research "
            "Fellowships, run by Royal Society Te Apārangi with MBIE "
            "funding, which replaced the former Rutherford Discovery, "
            "Rutherford Foundation, and James Cook Research Fellowship "
            "schemes (all ended in 2023). Eligible applicants must hold "
            "a PhD (or have completed all requirements for one to be "
            "conferred at the time of application) and be supported by "
            "a New Zealand-based research organisation; no nationality "
            "restriction is stated. The 2026 application portal opens 1 "
            "May 2026 and closes 9 July 2026, 2:00pm (NZST); subsequent "
            "cycles follow a similar annual schedule. Full terms of "
            "reference are published at "
            "https://www.royalsociety.org.nz/what-we-do/funds-and-"
            "opportunities/tawhia-te-mana/."
        ),
    },
    {
        "title":   "Mana Tūārangi Distinguished Researcher Fellowship",
        "url":     BASE + "mana-tuarangi",
        "portal":  PORTAL,
        "deadline": _DEADLINE,
        "open_threshold_days": _OPEN_THRESHOLD_DAYS,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Senior Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "NZD",
        "sectors": ["Science & Technology", "Research & Innovation"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["NZ"],
        "desc": (
            "The New Zealand Mana Tūārangi Distinguished Researcher "
            "Fellowship supports researchers with expansive, "
            "international, and transdisciplinary reputations to make "
            "continued, significant contributions to Aotearoa New "
            "Zealand's research system. It is one of three tiers within "
            "the Tāwhia te Mana Research Fellowships, run by Royal "
            "Society Te Apārangi with MBIE funding, which replaced the "
            "former Rutherford Discovery, Rutherford Foundation, and "
            "James Cook Research Fellowship schemes (all ended in "
            "2023). Eligible applicants must hold a PhD and be "
            "supported by a New Zealand-based research organisation; no "
            "nationality restriction is stated. The 2026 application "
            "portal opens 1 May 2026 and closes 9 July 2026, 2:00pm "
            "(NZST); subsequent cycles follow a similar annual "
            "schedule. Full terms of reference are published at "
            "https://www.royalsociety.org.nz/what-we-do/funds-and-"
            "opportunities/tawhia-te-mana/."
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
    parser = argparse.ArgumentParser(description="Tāwhia te Mana (NZ) connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Tāwhia te Mana (NZ) — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Tāwhia te Mana: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
