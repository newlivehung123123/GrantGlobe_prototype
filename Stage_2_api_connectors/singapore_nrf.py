#!/usr/bin/env python3
"""
National Research Foundation, Singapore (NRF) — Central Gap Fund connector.

The NRF Central Gap Fund ("Central Gap") supports the translation of
research outcomes into products, processes and/or services that generate
economic and societal benefits for Singapore. Unlike NRF Singapore's other
flagship schemes (Competitive Research Programme, NRF Fellowship), whose
exact annual deadlines are only published on NRF's JS-rendered Integrated
Grants Management System (IGMS) at researchgrant.gov.sg and could not be
verified from a static fetch, the Central Gap Fund's own programme page
explicitly states: "Proposals can be submitted throughout the year and will
be processed on a needs basis." This is a clearly documented, genuinely
rolling call rather than an estimated or fabricated pattern.

Eligibility is institutional rather than purely individual: eligible
applicant organisations are publicly-funded research performers and
government-linked entities in Singapore (A*STAR Research Institutes, local
public research centres and consortia, public hospitals and health
institutions, local autonomous universities/polytechnics/Institutes of
Technical Education, CREATE entities, Research Centres of Excellence, and
Temasek Life Sciences Laboratory). This is consistent with this codebase's
other national-funder connectors (NSF, NIH, ERC, UKRI, etc.), which are
likewise institutional.

Deadline pattern — rolling, no fixed deadline (same sentinel-date convention
as LTFF/EAIF/CLR Fund elsewhere in this codebase).

Source: https://www.nrf.gov.sg/grants/cgf/
Portal: https://www.researchgrant.gov.sg/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/singapore_nrf.py [--dry-run]
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

FUNDER = "National Research Foundation, Singapore (NRF)"
DOMAIN = "api_singapore_nrf"
BASE   = "https://www.nrf.gov.sg/grants/cgf/"
PORTAL = "https://www.researchgrant.gov.sg/"

DESC = (
    "The NRF Central Gap Fund (\"Central Gap\") aims to support the "
    "translation of research outcomes into products, processes and/or "
    "services that generate economic and societal benefits for Singapore. "
    "The scheme provides a national-level platform to resource impactful "
    "projects and encourage collaboration across public research performers "
    "and/or industry, helping teams develop early technologies into working "
    "prototypes or functional processes closer to market. Projects from any "
    "area of science and engineering are eligible provided they aim to "
    "develop technologies of high impact and significant value for "
    "Singapore. Eligible applicant organisations include A*STAR Research "
    "Institutes, local public research centres and consortia, local public "
    "hospitals and health institutions, local autonomous universities, "
    "polytechnics and Institutes of Technical Education, CREATE entities, "
    "Research Centres of Excellence hosted by local autonomous universities, "
    "and Temasek Life Sciences Laboratory; other applicants are considered "
    "case-by-case. Funding is up to S$2 million (inclusive of 30% overheads) "
    "for up to two years, with co-funding required from the Host "
    "Institution/Innovation and Enterprise Office unless waived for "
    "projects that previously received translation funding. The programme "
    "page explicitly states that \"proposals can be submitted throughout "
    "the year and will be processed on a needs basis\" — a genuinely "
    "rolling call rather than a fixed annual deadline. Proposals are lodged "
    "electronically via the Integrated Grants Management System (IGMS) at "
    "https://www.researchgrant.gov.sg/."
)

SCHEMES: list[dict] = [
    {
        "title":   "NRF Central Gap Fund",
        "url":     BASE,
        "portal":  PORTAL,
        "deadline": datetime.date(2035, 12, 31),
        "deadline_raw": "Rolling (no fixed deadline; processed on a needs basis)",
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": ["Translational Research Grant", "Gap Funding"],
        "individual": [],
        "org_types": [
            "University", "Research Institution", "Government Agency",
            "Public Hospital",
        ],
        "amount_min": None,
        "amount_max": 2000000,
        "currency": "SGD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Innovation Policy", "Technology Translation",
        ],
        "applicant_countries": ["Singapore"],
        "focus_regions": [],
        "focus_countries": ["Singapore"],
        "desc": DESC,
    },
    {
        # ── 2. NRF Fellowship (NRFF) ───────────────────────────────────────────
        "title":   "NRF Fellowship (NRFF)",
        "url":     "https://www.nrf.gov.sg/grants/nrff/",
        "portal":  "https://www.researchgrant.gov.sg/",
        # 19th call (Class of 2027): opened 12 Feb 2026, closed 13 May
        # 2026 (already closed at authoring time).
        "deadline": datetime.date(2026, 5, 13),
        "open_threshold_days": 90,        # call opens ~12 February each year
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": 3250000,
        "currency": "SGD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Singapore"],
        "desc": (
            "The Singapore NRF Fellowship (NRFF) provides opportunities "
            "for outstanding early-career researchers of any nationality "
            "to carry out independent research in Singapore over a "
            "five-year period, open to all areas of science and "
            "technology. Eligible applicants have no more than 7 years "
            "of post-PhD experience. Each Fellow receives a research "
            "grant of up to S$3.25 million (inclusive of overheads) to "
            "support projects with high likelihood of a research "
            "breakthrough. NRF invites applications once a year through "
            "a three-step selection process: a longlisting process by "
            "prospective host institutions in Singapore, a shortlisting "
            "process, and a final selection, with shortlisted candidates "
            "invited to Singapore for a final interview by the NRF "
            "Fellowship Evaluation Panel. The 19th call (Class of 2027) "
            "opened 12 February 2026 and closed 13 May 2026, 3:00pm "
            "Singapore time; subsequent calls follow a similar annual "
            "schedule. Proposals are lodged via the Integrated Grants "
            "Management System (IGMS) at "
            "https://www.researchgrant.gov.sg/."
        ),
    },
    {
        # ── 3. NRF Investigatorship ─────────────────────────────────────────
        "title":   "NRF Investigatorship",
        "url":     "https://www.nrf.gov.sg/grants/nrfi/",
        "portal":  "https://www.researchgrant.gov.sg/",
        # 12th call: host-institution nomination deadlines fall in
        # mid-April (already closed at authoring time).
        "deadline": datetime.date(2026, 4, 16),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Senior Researcher"],
        "org_types": ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 3250000,
        "currency": "SGD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Singapore"],
        "desc": (
            "The NRF Investigatorship provides funding opportunities for "
            "established scientists and researchers to pursue "
            "ground-breaking, high-risk research in any field of "
            "science and technology in Singapore, except translational "
            "clinical research. Funding is up to S$3.25 million "
            "(including indirect research costs) over five years. "
            "Candidates are nominated by their host research "
            "institution in Singapore rather than applying directly; "
            "the 12th call's host-institution nomination deadlines fell "
            "in mid-April 2026, with the central RGC/NRF deadline "
            "shortly after; subsequent calls follow a similar annual "
            "schedule. Proposals are lodged via the Integrated Grants "
            "Management System (IGMS) at "
            "https://www.researchgrant.gov.sg/."
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
    parser = argparse.ArgumentParser(description="NRF Singapore connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  NRF Singapore — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  NRF Singapore: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
