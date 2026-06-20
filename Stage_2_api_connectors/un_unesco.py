#!/usr/bin/env python3
"""
UNESCO connector.

UNESCO publishes more than 450 annual fellowships, but the overwhelming
majority are co-sponsored bilateral programmes (e.g. UNESCO/China — The
Great Wall, UNESCO/Poland, UNESCO/Saudi Arabia — AlUla), each with its
own country-specific deadline and host-country placement, structurally
similar to the fragmentation found in Japan's MEXT scholarship (no single
global deadline; dozens of country/theme-specific calls). This connector
instead covers UNESCO's two genuinely global, non-bilateral award
programmes:

1. L'Oréal-UNESCO For Women in Science International Awards — recognises
   five outstanding women scientists globally each year (rotating
   through scientific disciplines), one from each major world region.
   Note: this is a nomination-based award (eminent scientists nominate
   candidates; self-nominations are not accepted), not a direct
   application.

2. UNESCO MAB (Man and the Biosphere) Young Scientist Awards — supports
   early-career researchers (35 or under) conducting research on
   ecosystems, biodiversity, and sustainability, with priority given to
   projects in UNESCO biosphere reserves. Applicants from developed
   countries are eligible only in exceptional cases or when collaborating
   with developing-country researchers.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.unesco.org/en/fellowships
Portal: https://www.unesco.org/en/applications-and-nominations

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/un_unesco.py [--dry-run]
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

FUNDER = "UNESCO"
DOMAIN = "api_un_unesco"

SCHEMES: list[dict] = [
    {
        "title":   "L'Oréal-UNESCO For Women in Science International Awards",
        "url":     "https://www.unesco.org/en/prizes/women-science",
        "portal":  "https://www.forwomeninscience.com/",
        # 2027 cohort: nomination deadline 30 June 2026.
        "deadline": datetime.date(2026, 6, 30),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Award", "Prize"],
        "individual": ["Senior Researcher"],
        "org_types": [],
        "amount_min": 100000,
        "amount_max": 100000,
        "currency": "EUR",
        "sectors": [
            "Science & Technology", "Mathematics", "Physics",
            "Computer Science", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": (
            "The L'Oréal-UNESCO For Women in Science International "
            "Awards recognise five outstanding women scientists "
            "globally each year for excellence in research and "
            "scientific impact, each working in one of five world "
            "regions (Africa and the Arab States; Asia and the Pacific; "
            "Europe; Latin America and the Caribbean; North America). "
            "Each laureate receives €100,000. The scientific discipline "
            "honoured rotates each year; the 2027 International Awards "
            "will honour researchers in Physical Sciences, Mathematics, "
            "and Computer Science. This is a nomination-based award: "
            "eminent scientists nominate eligible candidates through an "
            "online platform, and self-nominations or nominations from "
            "immediate family members are not accepted. Candidates are "
            "assessed on the excellence of their scientific "
            "contributions, the impact of their research, and their "
            "influence within the international scientific community. "
            "The 2027 cycle's nomination deadline is 30 June 2026; "
            "subsequent cycles follow a similar annual schedule. Full "
            "details are published at "
            "https://www.unesco.org/en/prizes/women-science and "
            "https://www.forwomeninscience.com/."
        ),
    },
    {
        "title":   "UNESCO MAB Young Scientist Awards",
        "url":     "https://www.unesco.org/en/mab/young-scientists",
        "portal":  "https://www.unesco.org/en/applications-and-nominations",
        # 2026 cycle deadline: 7 May 2026 (already closed at authoring
        # time).
        "deadline": datetime.date(2026, 5, 7),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Award"],
        "individual": ["Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": 5000,
        "currency": "USD",
        "sectors": [
            "Environmental Science", "Biodiversity",
            "Ecosystem Management", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": (
            "The UNESCO Man and the Biosphere (MAB) Young Scientist "
            "Awards support early-career researchers conducting "
            "research on ecosystems, biodiversity, and sustainability, "
            "with priority given to projects carried out in UNESCO "
            "biosphere reserves. Applicants must be 35 years old or "
            "younger at the application deadline; applicants from "
            "developed countries are eligible only in exceptional cases "
            "or when collaborating with researchers from developing "
            "countries. Applications must be endorsed by the "
            "applicant's MAB National Committee. Awards are set at a "
            "maximum of US$5,000 each, and research supported by an "
            "award should be completed within two years. The 2026 "
            "cycle's deadline was 7 May 2026; subsequent cycles follow "
            "a similar annual schedule. Full details are published at "
            "https://www.unesco.org/en/mab/young-scientists. Inquiries: "
            "mab.awards@unesco.org."
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
    parser = argparse.ArgumentParser(description="UNESCO connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  UNESCO — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  UNESCO: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
