#!/usr/bin/env python3
"""
Romania — UEFISCDI (Executive Agency for Higher Education, Research,
Development and Innovation Funding) connector.

UEFISCDI runs Romania's national competitive research grant
competitions (the "PN IV" programme) on behalf of the National
Authority for Research (ANC). This connector covers two of its
real, currently-running 2026 calls, each verified directly from
UEFISCDI's own call pages (with the National Authority for Research's
approval decision numbers):

1. PCE (Proiecte de Cercetare Exploratorie) 2026 — Exploratory
   Research Projects — explicitly addressed to researchers with
   internationally recognised performance, including those working
   abroad (Romanian citizens or foreigners), who wish to lead
   high-level scientific research projects at institutions in
   Romania. Approved by ANC Decision no. 20324/04.06.2026.

2. TE (Proiecte de cercetare pentru stimularea tinerelor echipe
   independente) 2026 — Young Independent Teams — supports early-career
   researchers who have established an independent research programme
   and significant results, to build or strengthen their own research
   team at a Romanian host institution. Approved by ANC Decision no.
   20325/04.06.2026.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://uefiscdi.gov.ro/proiecte-de-cercetare-exploratorie-pce
         https://uefiscdi.gov.ro/proiecte-de-cercetare-pentru-stimularea-tinerelor-echipe-independente-te
Portal: https://uefiscdi-direct.ro/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/romania_uefiscdi.py [--dry-run]
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

FUNDER = "UEFISCDI (Romania)"
DOMAIN = "api_romania_uefiscdi"
PORTAL = "https://uefiscdi-direct.ro/"

SCHEMES: list[dict] = [
    {
        "title":   "PCE (Exploratory Research Projects) 2026",
        "url":     "https://uefiscdi.gov.ro/proiecte-de-cercetare-exploratorie-pce",
        "portal":  PORTAL,
        # 2026 cycle: online submission opens 23 June 2026, deadline
        # 31 July 2026, 16:00 (local time).
        "deadline": datetime.date(2026, 7, 31),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "RON",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["RO"],
        "desc": (
            "PCE (Proiecte de Cercetare Exploratorie / Exploratory "
            "Research Projects) supports and promotes fundamental "
            "and/or exploratory scientific research in Romania. The "
            "programme is explicitly addressed to researchers with "
            "internationally recognised performance, demonstrated by "
            "the quality and international recognition of their "
            "scientific results — including those currently working "
            "abroad, whether Romanian citizens or foreign nationals — "
            "who wish to lead high-level scientific research projects "
            "at institutions in Romania. The 2026 cycle (total budget "
            "RON 80,000,000 / EUR 16,000,000), approved by National "
            "Authority for Research Decision no. 20324/04.06.2026, "
            "opens its online submission platform on 23 June 2026 with "
            "a deadline of 31 July 2026, 16:00 local time; subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://uefiscdi.gov.ro/proiecte-de-"
            "cercetare-exploratorie-pce."
        ),
    },
    {
        "title":   "TE (Young Independent Teams Research Projects) 2026",
        "url":     "https://uefiscdi.gov.ro/proiecte-de-cercetare-pentru-stimularea-tinerelor-echipe-independente-te",
        "portal":  PORTAL,
        # 2026 cycle: online submission opens 23 June 2026, deadline
        # 30 July 2026, 16:00 (local time).
        "deadline": datetime.date(2026, 7, 30),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "RON",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["RO"],
        "desc": (
            "TE (Proiecte de cercetare pentru stimularea tinerelor "
            "echipe independente / Young Independent Teams) supports "
            "young researchers who hold a PhD and have already "
            "established an independent research programme with "
            "significant results in their field, to create or "
            "strengthen their own research team at a Romanian host "
            "institution. The 2026 cycle (total budget RON 52,000,000 "
            "/ EUR 10,400,000), approved by National Authority for "
            "Research Decision no. 20325/04.06.2026, opens its online "
            "submission platform on 23 June 2026 with a deadline of 30 "
            "July 2026, 16:00 local time; subsequent cycles follow a "
            "similar annual schedule. Full guidelines are published at "
            "https://uefiscdi.gov.ro/proiecte-de-cercetare-pentru-"
            "stimularea-tinerelor-echipe-independente-te."
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
    parser = argparse.ArgumentParser(description="Romania UEFISCDI connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Romania UEFISCDI — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Romania UEFISCDI: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
