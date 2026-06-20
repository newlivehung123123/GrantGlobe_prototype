#!/usr/bin/env python3
"""
Tsinghua University — Shuimu Tsinghua Scholar Program connector.

The Shuimu Tsinghua Scholar Program is Tsinghua University's flagship
postdoctoral recruitment programme, open to global recruitment across 52
academic disciplines (science, engineering, humanities, and social
sciences). Eligibility is based solely on having obtained (or being about
to obtain) a PhD within the last three years — no institutional
affiliation beyond the applicant's own doctorate is required, and the
programme is explicitly described as a "Global Recruitment" exercise
open to scholars worldwide. Application materials (the application form,
academic/research materials, and recommendation letters) are submitted in
English or Chinese — application forms are explicitly published for both
"Overseas PhD" and "Domestic PhD" applicant tracks.

The programme runs two recruitment rounds per year: a first round (Round
1, departmental recommendations due 10 April) and a second round (Round 2,
departmental recommendations due 10 October). This connector models each
round as a separate scheme using the annual cyclical-advance pattern.

Source: https://postdoctor.tsinghua.edu.cn/info/zxtz/2174
Portal: http://postdoctor.tsinghua.edu.cn/thu/index.htm

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/china_tsinghua.py [--dry-run]
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

FUNDER = "Tsinghua University — Shuimu Tsinghua Scholar Program"
DOMAIN = "api_china_tsinghua_shuimu"
BASE   = "https://postdoctor.tsinghua.edu.cn/info/zxtz/2174"
PORTAL = "http://postdoctor.tsinghua.edu.cn/thu/index.htm"

DESC = (
    "The Shuimu Tsinghua Scholar Program is Tsinghua University's "
    "postdoctoral recruitment programme, open to global recruitment "
    "across 52 academic disciplines spanning science, engineering, "
    "humanities, and social sciences. Eligibility requires that the "
    "applicant has obtained, or will shortly obtain, a PhD within the "
    "past three years, recommendation by departmental interview, and a "
    "commitment to work full-time at Tsinghua University. Scholars "
    "receive an annual pre-tax salary of 300,000 RMB for a two- or "
    "three-year appointment, transitional campus housing or a housing "
    "subsidy of 42,000 RMB per year, medical coverage equivalent to "
    "Tsinghua faculty, access to Tsinghua's kindergarten and primary "
    "school for their children, and funding for top-level international "
    "conference attendance. Application materials — the Shuimu Tsinghua "
    "Scholar Program Application Form, academic/research materials, and "
    "2-3 letters of recommendation including one from the applicant's "
    "PhD advisor — are accepted in English or Chinese; separate "
    "application-form templates are published for overseas-PhD and "
    "domestic-PhD applicant tracks. Recruitment runs in two annual "
    "rounds. Materials are compiled into a single PDF and emailed "
    "directly to the relevant department; recommendation letters are "
    "sent by referees directly to the department's email address. "
    "Full department contact details are listed at "
    "http://postdoctor.tsinghua.edu.cn/."
)

SCHEMES: list[dict] = [
    {
        "title":    "Shuimu Tsinghua Scholar Program — Round 1",
        "url":      BASE,
        "portal":   PORTAL,
        # Round 1: department recommendations due 10 April each year.
        "deadline": datetime.date(2026, 4, 10),
        "open_threshold_days": 40,        # submission opens ~March each year
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  [],
        "amount_min": 300000,
        "amount_max": 300000,
        "currency":   "CNY",
        "sectors": [
            "Science & Technology", "Engineering", "Humanities",
            "Social Sciences", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["CN"],
        "desc": DESC,
    },
    {
        "title":    "Shuimu Tsinghua Scholar Program — Round 2",
        "url":      BASE,
        "portal":   PORTAL,
        # Round 2: department recommendations due 10 October each year.
        "deadline": datetime.date(2026, 10, 10),
        "open_threshold_days": 40,        # submission opens ~September each year
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  [],
        "amount_min": 300000,
        "amount_max": 300000,
        "currency":   "CNY",
        "sectors": [
            "Science & Technology", "Engineering", "Humanities",
            "Social Sciences", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["CN"],
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
    cur.execute("SELECT id FROM grants WHERE source_url = %s", (db_rec["source_url"],))
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
    parser = argparse.ArgumentParser(description="Tsinghua Shuimu Scholar Program connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Tsinghua Shuimu Scholar Program — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Tsinghua Shuimu: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
