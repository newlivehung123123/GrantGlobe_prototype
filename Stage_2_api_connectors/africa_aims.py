#!/usr/bin/env python3
"""
AIMS (African Institute for Mathematical Sciences) connector.

AIMS is a pan-African network of postgraduate centres (Cameroon, Ghana,
Rwanda, Senegal, South Africa, Tanzania) offering fully funded master's
scholarships to African students in the mathematical sciences. This
connector covers AIMS's two verified, recurring, fully funded master's
scholarship programmes:

1. AIMS Master's in Mathematical Sciences (Structured Master's Program) —
   the institute's flagship one-year, fully funded master's degree, run
   across all AIMS centres.

2. AIMS Master's in Mathematical Epidemiology (MathEpi) — run in
   partnership with the University of Toronto, a 16-month programme
   equipping students with mathematical/statistical tools for public
   health.

(AIMS also runs the Master of Mathematical Sciences for Teachers (MMST)
and hosts the Next Einstein Forum (NEF) Fellows Programme; the latter
showcases Africa's leading young scientists but has no consistently
verifiable recurring application deadline at the time of writing and is
not included here. MMST is a not-yet-fully-verified third stream and is
flagged for a future pass.)

Eligibility for both schemes is restricted to African nationals — a
continent-wide eligibility scope, consistent with other Africa-focused
connectors in this project (TWAS, CODESRIA, AAS), rather than a
single-country restriction.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://nexteinstein.org/application/aims-masters-degree/
Portal: https://www.applications.aimsric.org

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/africa_aims.py [--dry-run]
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

FUNDER = "African Institute for Mathematical Sciences (AIMS)"
DOMAIN = "api_africa_aims"
BASE   = "https://nexteinstein.org/application/aims-masters-degree/"
PORTAL = "https://www.applications.aimsric.org"

SCHEMES: list[dict] = [
    {
        "title":   "AIMS Master's in Mathematical Sciences (Structured Master's Program)",
        "url":     BASE,
        "portal":  PORTAL,
        # 2026 cycle deadline: 17 October 2025 (already closed at
        # authoring time).
        "deadline": datetime.date(2025, 10, 17),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Scholarship"],
        "individual": ["Graduate Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Mathematics", "Science & Technology", "Engineering",
        ],
        "applicant_countries": [],
        "focus_regions": ["Africa"],
        "focus_countries": [],
        "desc": (
            "The AIMS Master's in Mathematical Sciences (Structured "
            "Master's Program) is a fully funded, one-year postgraduate "
            "degree offered across AIMS's network of centres in "
            "Cameroon, Ghana, Rwanda, Senegal, South Africa, and "
            "Tanzania. The scholarship covers tuition, accommodation, "
            "meals, and health insurance for all selected candidates. "
            "Applicants must hold, or expect to obtain by the start of "
            "training, a four-year university degree in mathematics or "
            "another science/engineering discipline with a significant "
            "mathematics component, and must be African nationals. The "
            "2026 cycle's deadline was 17 October 2025; subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://nexteinstein.org/application/"
            "aims-masters-degree/."
        ),
    },
    {
        "title":   "AIMS Master's in Mathematical Epidemiology (MathEpi)",
        "url":     "https://www.applications.aimsric.org",
        "portal":  PORTAL,
        # 2026 cycle deadline: 15 March 2026 (already closed at
        # authoring time).
        "deadline": datetime.date(2026, 3, 15),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Scholarship"],
        "individual": ["Graduate Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Mathematics", "Public Health", "Epidemiology",
            "Statistics & Data Science",
        ],
        "applicant_countries": [],
        "focus_regions": ["Africa"],
        "focus_countries": [],
        "desc": (
            "The AIMS Master's in Mathematical Epidemiology (MathEpi), "
            "run in partnership with the University of Toronto, is a "
            "fully funded 16-month programme equipping students with "
            "advanced mathematical and statistical tools for addressing "
            "real-world public health challenges. The scholarship "
            "covers tuition and academic fees, accommodation and meals, "
            "and health insurance. Applicants must be African nationals "
            "holding a bachelor's or master's degree in mathematical "
            "sciences (including Statistics, Data Science, Computer "
            "Science, Physics, or Engineering) with a significant "
            "mathematical component. The 2026 cycle's deadline was 15 "
            "March 2026; subsequent cycles follow a similar annual "
            "schedule. Applications are submitted online through "
            "https://www.applications.aimsric.org."
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
    parser = argparse.ArgumentParser(description="AIMS connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  AIMS — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  AIMS: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
