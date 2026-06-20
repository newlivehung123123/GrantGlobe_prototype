#!/usr/bin/env python3
"""
AXA Research Fund (AXA Foundation for Human Progress) connector.

A global academic research funder (not tied to any single country),
supporting research worldwide since 2008 across more than 750 projects in
39 countries. Eligibility is open to researchers and academic
institutions worldwide; the Fund explicitly does NOT support
associations, hospitals, foundations, NGOs, governmental bodies,
independent research centers, cultural institutions, or museums — only
academic research at universities/research institutions.

This connector covers the Fund's two flagship recurring programmes:

1. AXA Chairs — 5-year, up to €1.5M (€200,000/year) network grants led by
   senior researchers (PhD +10 years), transdisciplinary by design
   (combining at least one social science/humanities/economics
   discipline with at least one natural science/engineering/technology
   field), co-developed with non-academic partners.

2. AXA Post-Doctoral Fellowships — for early-career researchers, paid in
   four installments over the fellowship period.

A third programme, "New Gen" (for young researchers), was announced as a
forthcoming addition but had not yet opened with a deadline at the time
of writing; it is not included here and should be added once a concrete
call is published.

Deadline pattern — annual cycle, two-stage Expression of Interest then
full application (cyclical-advance, as in hhmi.py/fli.py; this connector
uses the Expression of Interest deadline as the operative date since that
is the first hard cutoff in the process).

Source: https://axa-research.org/fund-your-research
Portal: https://institution.axa-research.org/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/axa_research_fund.py [--dry-run]
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

FUNDER = "AXA Research Fund (AXA Foundation for Human Progress)"
DOMAIN = "api_axa_research_fund"
BASE   = "https://axa-research.org/fund-your-research"

SCHEMES: list[dict] = [
    {
        "title":   "AXA Chairs",
        "url":     "https://axa-research.org/fund-your-research/axa-chairs",
        "portal":  "https://institution.axa-research.org/",
        # 2026 cycle: Expression of Interest deadline ~10 October 2025
        # (already closed at authoring time; full applications followed
        # ~21 November 2025).
        "deadline": datetime.date(2025, 10, 10),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Chair"],
        "individual": ["Senior Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": 1500000,
        "amount_max": 1500000,
        "currency": "EUR",
        "sectors": [
            "Health Sciences", "Environmental Science",
            "Social Sciences", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": (
            "AXA Chairs are 5-year, up to €1.5 million (€200,000/year) "
            "network grants led by senior researchers (PhD obtained at "
            "least 10 years prior) to develop responses to systemic "
            "risks at the intersection of multiple disciplines, "
            "strengthening the link between science and society. Chairs "
            "are transdisciplinary by design, combining at least one "
            "social science, humanities, or economics discipline with "
            "at least one natural science, engineering, or technology "
            "field, and are co-developed and co-implemented with "
            "non-academic partners such as public authorities, NGOs, "
            "community organisations, or public hospitals. Applications "
            "are submitted by an academic institution on behalf of a "
            "candidate (institutions appoint an Operational Contact who "
            "registers on the AXA Research Fund's online platform); "
            "candidates cannot apply independently. The process has two "
            "stages: an Expression of Interest followed, for shortlisted "
            "candidates, by a full application. The Expression of "
            "Interest deadline for the 2026 cycle was 10 October 2025, "
            "with full applications due 21 November 2025; subsequent "
            "cycles follow a similar annual schedule. AXA grants are "
            "open to researchers and academic institutions worldwide; "
            "associations, hospitals (as standalone applicants), NGOs, "
            "governmental bodies, and museums are not eligible. Full "
            "guidelines are published at https://axa-research.org/"
            "fund-your-research/axa-chairs."
        ),
    },
    {
        "title":   "AXA Post-Doctoral Fellowships",
        "url":     "https://axa-research.org/fund-your-research/post-doctoral-fellowships",
        "portal":  "https://institution.axa-research.org/",
        # 2026 cycle: Expression of Interest deadline ~29 April 2025
        # (already closed at authoring time; full proposals followed
        # 19 May - 13 June 2025, rebuttals 24-30 September 2025).
        "deadline": datetime.date(2025, 4, 29),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": 125000,
        "amount_max": 125000,
        "currency": "EUR",
        "sectors": [
            "Health Sciences", "Environmental Science",
            "Social Sciences", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": (
            "AXA Post-Doctoral Fellowships support early-career "
            "researchers conducting academic research on systemic "
            "risks affecting human health, the planet, or society, "
            "within the AXA Research Fund's eligible thematic areas. "
            "The total fellowship value is paid in four installments "
            "over the project (approximately €35,000 at the 1-month "
            "mark, €35,000 at 12 months, €35,000 at 18 months, and a "
            "final €20,000 payment subject to the final report), "
            "totalling around €125,000. As with all AXA grants, "
            "applications are submitted by the host academic "
            "institution on behalf of the candidate via a two-stage "
            "process: an Expression of Interest, followed by a full "
            "research proposal for shortlisted candidates. The "
            "Expression of Interest deadline for the most recent cycle "
            "was 29 April 2025, 09:00 Swiss local time, with full "
            "proposals due 19 May-13 June 2025 and rebuttals 24-30 "
            "September 2025; subsequent cycles follow a similar annual "
            "schedule. AXA grants are open to researchers and academic "
            "institutions worldwide; associations, hospitals (as "
            "standalone applicants), NGOs, governmental bodies, and "
            "museums are not eligible. Full guidelines are published at "
            "https://axa-research.org/fund-your-research/"
            "post-doctoral-fellowships."
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
            "deadline_raw", f"{deadline.day} {deadline.strftime('%B %Y')} (Expression of Interest)"
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
    parser = argparse.ArgumentParser(description="AXA Research Fund connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  AXA Research Fund — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  AXA Research Fund: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
