#!/usr/bin/env python3
"""
Chiang Ching-kuo Foundation for International Scholarly Exchange (CCKF)
connector.

The Chiang Ching-kuo Foundation, based in Taipei, was established in 1989
to encourage scholars in Taiwan and overseas to undertake research
projects in the humanities and social sciences that shed new light on
Chinese culture and society, and to promote international scholarly
exchange. CCKF does not run a single grant call — its programmes are
organised into regular regional calls covering the American Region (US,
Canada, Mexico, Central/South America), the European Region, the
Asia-Pacific Region (Japan, Korea, Mongolia, the Philippines, Thailand,
Malaysia, Vietnam, Indonesia, Myanmar, Laos, Australia, and New Zealand),
and Developing Regions (Eastern/Central Europe, Southeast Asia, South
Asia, the Middle East, and Central Asia), each offering several grant
categories (Research Grants, Conference/Seminar Grants, Publication
Subsidies, Database Grants, Lecture Series Grants, and doctoral/
postdoctoral fellowships). This connector covers the flagship Research
Grant in each region plus the two categories most distinctly open to
individual researchers (the American Region's Doctoral Fellowships and the
European Region's combined PhD Dissertation and Postdoctoral Research
Fellowships, the latter carrying no nationality restriction).

Per the Foundation's own published schedule: applications for Conference/
Seminar Grants and Publication Subsidies run in two windows (1 Aug–15 Sep
and 1 Dec–15 Jan); the European Region's PhD Dissertation/Postdoctoral
Research Fellowships run 1 Dec–15 Jan; Hsu-Sun Scholarships run 1 Jul–31
Aug; and all other grants and fellowships (including each region's
Research Grants and the American Region's Doctoral Fellowships) run 1
Aug–15 Oct. Applications are submitted via CCKF's online Application
System.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: http://www.cckf.org/en/programs
Portal: http://application.cckf.org.tw/e-login.html

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/taiwan_cckf.py [--dry-run]
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

FUNDER = "Chiang Ching-kuo Foundation for International Scholarly Exchange (CCKF)"
DOMAIN = "api_taiwan_cckf"
BASE   = "http://www.cckf.org/en/programs"
PORTAL = "http://application.cckf.org.tw/e-login.html"

_COMMON_DESC_TAIL = (
    " Full application guidelines and category-specific eligibility are "
    "published at http://www.cckf.org/en/programs, with applications "
    "submitted via the Foundation's online Application System at "
    "http://application.cckf.org.tw/e-login.html."
)

SCHEMES: list[dict] = [
    {
        "title":    "CCKF Research Grants (American Region)",
        "url":      "http://www.cckf.org/en/programs/american",
        "portal":   PORTAL,
        "deadline": datetime.date(2026, 10, 15),
        "open_threshold_days": 75,        # application window opens 1 August
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher"],
        "org_types": ["University"],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": ["Chinese Studies", "Humanities", "Social Sciences"],
        "applicant_countries": ["US", "CA", "MX"],
        "focus_regions": [],
        "focus_countries": ["TW", "CN"],
        "desc": (
            "CCKF's American Region Research Grants support full-time "
            "faculty at academic institutions in the United States, "
            "Canada, Mexico, and Central or South America undertaking "
            "research in the humanities and social sciences that sheds "
            "new light on Chinese culture and society. The Foundation "
            "gives priority to projects collaborating with counterparts "
            "in Taiwan. The annual application window runs 1 August to "
            "15 October." + _COMMON_DESC_TAIL
        ),
    },
    {
        "title":    "CCKF Doctoral Fellowships (American Region)",
        "url":      "http://www.cckf.org/en/programs/american",
        "portal":   PORTAL,
        "deadline": datetime.date(2026, 10, 15),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Doctoral Fellowship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": 25000,
        "amount_max": 25000,
        "currency": "USD",
        "sectors": ["Chinese Studies", "Humanities", "Social Sciences"],
        "applicant_countries": ["US", "CA", "MX"],
        "focus_regions": [],
        "focus_countries": ["TW", "CN"],
        "desc": (
            "CCKF's American Region Doctoral Fellowships provide up to "
            "US$25,000 (paid in two installments) for one year of "
            "dissertation research in Chinese Studies. Eligibility is "
            "restricted to non-ROC (Republic of China) citizens who are "
            "doctoral candidates at accredited universities in the "
            "United States, Canada, Mexico, or Central or South America, "
            "in the final year of their doctoral programme, with the "
            "dissertation expected to be completed within the grant "
            "period. The annual application window runs 1 August to 15 "
            "October." + _COMMON_DESC_TAIL
        ),
    },
    {
        "title":    "CCKF Research Grants (European Region)",
        "url":      "http://www.cckf.org/en/programs/european",
        "portal":   PORTAL,
        "deadline": datetime.date(2026, 10, 15),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher"],
        "org_types": ["University"],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": ["Chinese Studies", "Humanities", "Social Sciences"],
        "applicant_countries": [],
        "focus_regions": ["Europe"],
        "focus_countries": ["TW", "CN"],
        "desc": (
            "CCKF's European Region Research Grants support full-time "
            "faculty at academic institutions in Europe undertaking "
            "research in the humanities and social sciences that sheds "
            "new light on Chinese culture and society, with priority "
            "given to projects collaborating with counterparts in "
            "Taiwan. The annual application window runs 1 August to 15 "
            "October." + _COMMON_DESC_TAIL
        ),
    },
    {
        "title":    "CCKF Fellowships for PhD Dissertations and Postdoctoral Research (European Region)",
        "url":      "http://www.cckf.org/en/programs/european",
        "portal":   PORTAL,
        # European-region PhD/postdoctoral fellowships have their own
        # window: 1 December - 15 January.
        "deadline": datetime.date(2027, 1, 15),
        "open_threshold_days": 45,        # application window opens 1 December
        "cycle_years": 1,
        "grant_types": ["Doctoral Fellowship", "Postdoctoral Fellowship"],
        "individual": ["PhD Student", "Postdoctoral Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": ["Chinese Studies", "Humanities", "Social Sciences"],
        "applicant_countries": [],
        "focus_regions": ["Europe"],
        "focus_countries": ["TW", "CN"],
        "desc": (
            "CCKF's European Region runs combined Fellowships for PhD "
            "Dissertations and Postdoctoral Research in Chinese Studies. "
            "Doctoral candidates who are non-ROC citizens enrolled at an "
            "accredited European university may apply for Doctoral "
            "Fellowships. Separately, junior scholars affiliated with an "
            "accredited university who received their PhD within five "
            "years of the application date and who do not hold a "
            "full-time salaried position may apply for Postdoctoral "
            "Research Fellowships — this postdoctoral category carries "
            "no nationality restriction. Priority is given to projects "
            "collaborating with counterparts in Taiwan. The annual "
            "application window runs 1 December to 15 "
            "January." + _COMMON_DESC_TAIL
        ),
    },
    {
        "title":    "CCKF Research Grants (Asia-Pacific Region)",
        "url":      "http://www.cckf.org/en/programs/apac",
        "portal":   PORTAL,
        "deadline": datetime.date(2026, 10, 15),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher"],
        "org_types": ["University"],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": ["Chinese Studies", "Humanities", "Social Sciences"],
        "applicant_countries": [
            "JP", "KR", "MN", "PH", "TH",
            "MY", "VN", "ID", "MM", "LA",
            "AU", "NZ",
        ],
        "focus_regions": [],
        "focus_countries": ["TW", "CN"],
        "desc": (
            "CCKF's Asia-Pacific Region Research Grants support "
            "full-time faculty at academic institutions in Japan, "
            "Korea, Mongolia, the Philippines, Thailand, Malaysia, "
            "Vietnam, Indonesia, Myanmar, Laos, Australia, or New "
            "Zealand undertaking research in the humanities and social "
            "sciences that sheds new light on Chinese culture and "
            "society, with priority given to projects collaborating "
            "with counterparts in Taiwan. The annual application window "
            "runs 1 August to 15 October." + _COMMON_DESC_TAIL
        ),
    },
    {
        "title":    "CCKF Research Grants (Developing Regions)",
        "url":      "http://www.cckf.org/en/programs/small_grants",
        "portal":   PORTAL,
        "deadline": datetime.date(2026, 10, 15),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "PhD Student"],
        "org_types": ["University"],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": ["Chinese Studies", "Humanities", "Social Sciences"],
        "applicant_countries": [],
        "focus_regions": [
            "Eastern Europe", "Central Europe", "Southeast Asia",
            "South Asia", "Middle East", "Central Asia",
        ],
        "focus_countries": ["TW", "CN"],
        "desc": (
            "CCKF's Developing Regions programme supports the "
            "development of new Chinese Studies programmes in regions "
            "that have only recently launched such undertakings, "
            "limited to countries in Eastern and Central Europe, "
            "Southeast Asia, South Asia, the Middle East, and Central "
            "Asia. Both full-time faculty and graduate students are "
            "welcome to apply for Research Grants (alongside Lecture "
            "Series Grants, Conference and Seminar Grants, Library "
            "Acquisition Grants, and Mobility Grants offered under the "
            "same programme). Applications are reviewed by a committee "
            "of scholars familiar with the academic environments of the "
            "covered regions, with priority given to projects "
            "collaborating with counterparts in Taiwan. The annual "
            "application window runs 1 August to 15 "
            "October." + _COMMON_DESC_TAIL
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
    parser = argparse.ArgumentParser(description="CCKF connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  CCKF — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  CCKF: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
