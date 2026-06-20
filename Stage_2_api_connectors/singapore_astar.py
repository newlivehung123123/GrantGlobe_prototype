#!/usr/bin/env python3
"""
Agency for Science, Technology and Research (A*STAR), Singapore connector.

A*STAR is Singapore's lead public sector R&D agency and a funder distinct
from the National Research Foundation (NRF) — see singapore_nrf.py for the
NRF Central Gap Fund. A*STAR publishes a live "Ongoing Grant Calls" table on
its own funding-opportunities page listing every currently open call by
name, opening date, and closing date. As of this connector's authoring date,
two calls are listed there:

1. MTC Young Individual Research Grant (YIRG) — an annual call (the page
   table is updated in place each year; the 2026 call opened 5 May 2026 and
   closes 23 June 2026, 11:59pm Singapore time) for Singapore-based
   early-career researchers (PhD obtained no more than 7 years prior) in
   physical sciences and engineering, holding a primary appointment of at
   least 75% at a local publicly-funded institution (NUS, NTU, A*STAR
   Research Entities, or other Institutes of Higher Learning), subject to
   institutional quotas.

2. Industry Alignment Fund – Industry Collaboration Projects (IAF-ICP) — a
   pan-domain, institution-only scheme (companies cannot apply directly)
   that opened intake on 13 May 2026 with no fixed closing date listed on
   the live page, i.e. a rolling intake rather than a single-round call.

Deadline pattern — YIRG uses the annual cyclical-advance pattern (as in
hhmi.py/fli.py); IAF-ICP uses the rolling sentinel-date pattern (as in
ltff.py/clr_fund.py) since A*STAR's own page lists no closing date for it.

Source: https://www.a-star.edu.sg/Research/funding-opportunities
Portal: https://igrants-app.a-star.edu.sg/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/singapore_astar.py [--dry-run]
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

FUNDER = "Agency for Science, Technology and Research (A*STAR), Singapore"
DOMAIN = "api_singapore_astar"
BASE   = "https://www.a-star.edu.sg/Research/funding-opportunities"
PORTAL = "https://igrants-app.a-star.edu.sg/"

SCHEMES: list[dict] = [
    {
        # ── 1. MTC Young Individual Research Grant (YIRG) ─────────────────────
        "title":    "A*STAR MTC Young Individual Research Grant (YIRG)",
        "url":      "https://www.a-star.edu.sg/Research/funding-opportunities/yirg",
        "portal":   PORTAL,
        # 2026 call: opens 5 May 2026, closes 23 Jun 2026 (11:59pm SGT).
        "deadline": datetime.date(2026, 6, 23),
        "open_threshold_days": 50,        # call opens ~5 May each year
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 325000,
        "currency":   "SGD",
        "sectors": [
            "Physical Sciences", "Engineering", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": ["SG"],
        "focus_regions":       [],
        "focus_countries":     ["SG"],
        "desc": (
            "The Manufacturing, Trade & Connectivity Young Individual "
            "Research Grant (MTC YIRG) supports Singapore-based, "
            "early-career researchers for independent, curiosity-driven "
            "research in physical sciences and engineering areas. Funding "
            "of up to S$325,000 per project (inclusive of 30% indirect "
            "costs) is available for a project duration of up to three "
            "years. Eligibility requires a PhD obtained no more than 7 "
            "years prior, with the Principal Investigator holding a "
            "primary appointment of at least 75% (minimum 9 months' "
            "employment per year) at a local publicly-funded institution "
            "throughout the project. Institutional quotas apply per grant "
            "call: 15 each from the National University of Singapore "
            "(NUS), Nanyang Technological University (NTU), and A*STAR "
            "Research Entities, plus 2 from other public-sector "
            "Institutes of Higher Learning. Awardees of the NRF "
            "Fellowship, MOE Tier 2/3 grants, or MOH/NMRC IRG-equivalent "
            "grants are not eligible. Applications must be endorsed by "
            "the Host Institution's Research Director prior to "
            "submission, and are lodged through A*STAR's IGrants system "
            "at https://igrants-app.a-star.edu.sg/."
        ),
    },
    {
        # ── 2. Industry Alignment Fund – Industry Collaboration Projects ──────
        "title":    "A*STAR Industry Alignment Fund – Industry Collaboration Projects (IAF-ICP)",
        "url":      "https://www.a-star.edu.sg/Research/funding-opportunities/iaf-icp",
        "portal":   PORTAL,
        "deadline": datetime.date(2035, 12, 31),
        "deadline_raw": "Rolling intake (opened 13 May 2026; no fixed closing date)",
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": ["Industry Collaboration Grant"],
        "individual": [],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "SGD",
        "sectors": [
            "Research & Innovation", "Industry Collaboration",
            "Technology Translation", "Innovation Policy",
        ],
        "applicant_countries": ["SG"],
        "focus_regions": [],
        "focus_countries": ["SG"],
        "desc": (
            "The Industry Alignment Fund – Industry Collaboration Projects "
            "(IAF-ICP) is a pan-domain grant scheme that supports public "
            "research performers in strategic R&D projects with industry, "
            "fostering industry-relevant public sector R&D with a line of "
            "sight to commercialisation and/or deployment. It is governed "
            "by an Implementing Agency comprising the Singapore Economic "
            "Development Board and Enterprise Singapore, with grant "
            "administration supported by A*STAR's Office of Grants "
            "Administration. IAF-ICP is open only to Public Research "
            "Institutions in Singapore; companies are not eligible to "
            "apply directly or as co-applicants, and applications "
            "submitted directly by individual researchers are not "
            "accepted. Performers must secure Industry Partners willing "
            "to commit R&D spending (cash and in-kind) to the project. "
            "Projects are recommended not to exceed 36 months (up to 60 "
            "months for Corporate Laboratories). A*STAR's own funding "
            "page lists this intake as open from 13 May 2026 with no "
            "fixed closing date, i.e. a rolling rather than single-round "
            "call. Applications are submitted directly to the IAF-ICP "
            "Grant Intermediary (A*STAR OGA) following endorsement by "
            "the applicant institution's Research Office and Innovation "
            "& Enterprise Office."
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
        # internal — stripped before DB write
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
    parser = argparse.ArgumentParser(description="A*STAR Singapore connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  A*STAR Singapore — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  A*STAR Singapore: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
