#!/usr/bin/env python3
"""
Sweden — Vetenskapsrådet (Swedish Research Council, VR) connector.

VR is Sweden's main public research funding agency. This connector
covers two of its programmes:

1. VR Research Project Grant — VR's flagship annual competitive
   research project grant, open to researchers holding a Swedish
   doctoral degree or an equivalent foreign degree, hosted at a
   Swedish higher education institution or other eligible Swedish
   research-performing organisation. (Note: this requires a Swedish
   host institution and supervising organisation, but eligibility is
   based on the host/applicant's degree and institutional affiliation
   rather than nationality — an equivalent foreign doctoral degree is
   explicitly accepted.)

2. VR Grant for Recruiting International Visiting Researchers to
   Sweden — explicitly designed for Swedish research-performing
   organisations to recruit and host international visiting
   researchers, with a long rolling application window each year.

(VR's site is largely JavaScript-rendered, which is why this connector
uses the static-template pattern, similar to wellcome.py/snsf_switzerland.py,
rather than a live scraper.)

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.vr.se/english/applying-for-funding/calls.html
Portal: https://www.vr.se/english/applying-for-funding/calls.html

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/sweden_vr.py [--dry-run]
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

FUNDER = "Swedish Research Council (Vetenskapsrådet, VR)"
DOMAIN = "api_sweden_vr"
BASE   = "https://www.vr.se/english/applying-for-funding/calls.html"

SCHEMES: list[dict] = [
    {
        "title":   "VR Research Project Grant",
        "url":     BASE,
        "portal":  BASE,
        # 2026 cycle deadline: 10 February 2026, 14:00 CET (already
        # closed at authoring time).
        "deadline": datetime.date(2026, 2, 10),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": 400000,
        "amount_max": 1700000,
        "currency": "SEK",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Medicine & Health", "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["SE"],
        "desc": (
            "The VR Research Project Grant is the Swedish Research "
            "Council's flagship annual competitive grant for "
            "independent, high-quality research projects, running one "
            "to four years (most commonly three). Applicants must hold "
            "a Swedish doctoral degree or an equivalent foreign degree "
            "awarded no later than the application deadline, and must "
            "be hosted by a Swedish higher education institution or "
            "another organisation meeting VR's criteria for "
            "administering Swedish Research Council grants. Annual "
            "funding ranges from SEK 400,000 to SEK 1,700,000 including "
            "indirect costs. The 2026 cycle's deadline was 10 February "
            "2026, 14:00 CET; subsequent cycles follow a similar annual "
            "schedule. Full guidelines are published at "
            "https://www.vr.se/english/applying-for-funding/calls.html."
        ),
    },
    {
        "title":   "VR Grant for Recruiting International Visiting Researchers to Sweden",
        "url":     "https://www.vr.se/english/applying-for-funding/calls/2025-11-24-grant-for-recruiting-international-visiting-researchers-to-sweden-2026.html",
        "portal":  BASE,
        # 2026 cycle: rolling application window 11 February 2026 to
        # 10 November 2026; deadline modeled as the closing date of
        # that window.
        "deadline": datetime.date(2026, 11, 10),
        "open_threshold_days": 270,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "SEK",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Medicine & Health", "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["SE"],
        "desc": (
            "The VR Grant for Recruiting International Visiting "
            "Researchers to Sweden funds Swedish research-performing "
            "organisations to recruit and host international visiting "
            "researchers for a 12-month visit. Applications are "
            "accepted on a rolling basis throughout a long annual "
            "window; the 2026 cycle's window ran from 11 February 2026 "
            "to 10 November 2026, for visits starting no earlier than "
            "1 May 2026 and no later than 1 March 2027. Subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://www.vr.se/english/applying-for-"
            "funding/calls/2025-11-24-grant-for-recruiting-"
            "international-visiting-researchers-to-sweden-2026.html."
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
    parser = argparse.ArgumentParser(description="Sweden VR connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Sweden VR — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Sweden VR: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
