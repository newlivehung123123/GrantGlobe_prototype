#!/usr/bin/env python3
"""
Westlake University — Westlake Fellows Program connector.

Westlake University (Hangzhou, China) is a privately-funded research
university operating with English and Chinese as working languages. The
Westlake Fellows Program is its flagship independent-PI recruitment
programme for outstanding newly-minted or imminent PhD graduates (any area
of science and engineering) to establish their own independent research
programmes, rather than working under an existing supervisor — distinct
from the postdoctoral-fellow programmes covered by china_tsinghua.py and
china_pku_boya.py. Applicants must be about to receive, or have received
within the past two years, a PhD, and must not have held a tenure-track or
tenured faculty position.

The Spring 2026 round opened for nominations and applications on 1 January
2026 and closed 28 February 2026, with award announcements expected by 30
June 2026. The programme has run previous annual "Spring" rounds (e.g.
Spring 2025), so this connector models it as a single annual scheme using
the cyclical-advance pattern.

Source: https://westlakefellows.westlake.edu.cn/
Portal: https://westlakefellows.westlake.edu.cn/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/china_westlake.py [--dry-run]
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

FUNDER = "Westlake University — Westlake Fellows Program"
DOMAIN = "api_china_westlake_fellows"
BASE   = "https://westlakefellows.westlake.edu.cn/"
PORTAL = "https://westlakefellows.westlake.edu.cn/"

SCHEMES: list[dict] = [
    {
        "title":   "Westlake Fellows Program",
        "url":     BASE,
        "portal":  PORTAL,
        # Spring 2026 round: applications closed 28 February 2026.
        "deadline": datetime.date(2026, 2, 28),
        "open_threshold_days": 58,        # call opens ~1 January each year
        "cycle_years": 1,
        "grant_types": ["Independent Research Fellowship"],
        "individual": ["Early Career Researcher", "Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "CNY",
        "sectors": [
            "Science & Technology", "Engineering", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CN"],
        "desc": (
            "The Westlake Fellows Program is Westlake University's "
            "flagship recruitment programme for outstanding newly-minted "
            "or imminent PhD graduates with a track record of excellence "
            "and creativity, supporting them to establish their own "
            "independent research programmes at Westlake in any area of "
            "science and engineering — distinct from supervised "
            "postdoctoral-fellow positions. Westlake University, based "
            "in Hangzhou, China, operates with English and Chinese as "
            "working languages and offers a fully international research "
            "environment with strong institutional support for "
            "interdisciplinary collaboration. Fellows receive a highly "
            "competitive start-up package including research funding, "
            "salary, and benefits aligned with leading global standards. "
            "Eligible applicants must be about to receive a PhD, or have "
            "obtained one within the past two years as of the "
            "application deadline, and must not have held a tenure-track "
            "or tenured faculty position. The Spring 2026 round opened "
            "for nominations and applications on 1 January 2026 and "
            "closed 28 February 2026, with fellowship awards expected to "
            "be announced by 30 June 2026; the programme has run "
            "previous annual Spring rounds (e.g. Spring 2025) on a "
            "similar schedule. Application materials are submitted by "
            "email to WestlakeFellows@westlake.edu.cn."
        ),
    },
    {
        # ── 2. Westlake University International PhD Programs ────────────────
        "title":   "Westlake University International PhD Programs",
        "url":     "https://en.westlake.edu.cn/admissions/international_students/",
        "portal":  "https://en.westlake.edu.cn/admissions/international_students/",
        # Final application deadline: 31 March each year (Chemistry: 16
        # March).
        "deadline": datetime.date(2026, 3, 31),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["PhD Scholarship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "CNY",
        "sectors": [
            "Science & Technology", "Engineering", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CN"],
        "desc": (
            "Westlake University accepts international applicants "
            "holding a bachelor's degree directly into its PhD "
            "programmes, including newly launched programmes in "
            "Quantitative Biology and Complex Systems, Materials Science "
            "and Engineering, Information Technology in Artificial "
            "Intelligence, and Sustainability Science and Technology, "
            "alongside its existing science and engineering programmes. "
            "Every admitted international PhD student receives a full "
            "tuition waiver and a monthly stipend for the duration of "
            "their studies, with no application fee. The final "
            "application deadline is 31 March each year (16 March for "
            "the Chemistry programme specifically). Applications are "
            "submitted through Westlake's online international-student "
            "application portal."
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
    parser = argparse.ArgumentParser(description="Westlake Fellows Program connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Westlake Fellows Program — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Westlake Fellows: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
