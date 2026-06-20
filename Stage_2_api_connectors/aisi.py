#!/usr/bin/env python3
"""
AI Security Institute (AISI) connector.

The AI Security Institute (AISI) is a research directorate within the UK's
Department of Science, Innovation and Technology (DSIT). Its mission is to
enable advanced AI governance through rigorous research into AI safety and
security. AISI funds external research through major grant programmes with
dedicated focus areas.

To date AISI has run three large-scale grant programmes:

1. AISI Challenge Fund
   Awards up to £200,000 per project for research addressing pressing
   unresolved questions in AI safety and security. Open to UK and
   international academic institutions and non-profit organisations.
   First round launched 5 March 2025; currently closed. Next round
   estimated early 2027.

2. AISI Alignment Project (Alignment Fund)
   Awards up to £1 million per project for research to prevent advanced
   AI systems from behaving dangerously. 60 projects funded, £27m+ total
   in first cohort. Currently closed. Next round estimated early 2027.

3. AISI Systemic Safety Grants
   Aims to increase societal resilience to widespread AI deployment across
   sectors such as healthcare, energy grids, and financial markets. 20
   projects selected in first round, now underway. Next round estimated
   mid-2027.

All three programmes are currently closed. Deadlines below are forward
estimates used to flag these as Forthcoming in the pipeline so that
applicants are alerted when a new round opens.

Source: https://www.aisi.gov.uk/grants

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/aisi.py [--dry-run]
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

FUNDER  = "AI Security Institute (AISI)"
DOMAIN  = "api_aisi"
BASE    = "https://www.aisi.gov.uk/grants"
PORTAL  = "https://www.aisi.gov.uk/grants"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. AISI Challenge Fund ────────────────────────────────────────────
        "title":    "AISI Challenge Fund",
        "url":      BASE,
        "portal":   PORTAL,
        # First round launched 5 March 2025. Estimated annual recurrence.
        "deadline": datetime.date(2027, 3, 5),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Researcher", "Postdoctoral Researcher",
                       "Early Career Researcher", "Mid-Career Researcher",
                       "Senior Researcher"],
        "org_types":  ["University", "Research Institution",
                       "Non-Profit Organisation"],
        "amount_min": None,
        "amount_max": 200000,
        "currency":   "GBP",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Artificial Intelligence", "Cybersecurity",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The AISI Challenge Fund supports research to understand and tackle "
            "potential risks from advanced AI. It awards up to £200,000 per project "
            "to accelerate innovation across fields including safeguards, control, "
            "alignment, and societal resilience. AISI additionally provides some "
            "projects with compute resources and opportunities to collaborate with "
            "AISI experts. "
            "Eligible applicants include researchers based at UK and international "
            "academic institutions and registered non-profit organisations. The fund "
            "is process-based: Stage 1 involves submission of an eligibility statement "
            "and expression of interest, which is reviewed within two to four weeks. "
            "Shortlisted applicants then work with an AISI Research Sponsor to "
            "develop a full application (typically two weeks), with a funding decision "
            "within four weeks of full application submission. Payments are made in "
            "monthly arrears. "
            "AISI has identified priority research areas (published on its website); "
            "proposals addressing other AI safety and security topics are also "
            "welcome. The first round of the Challenge Fund launched on 5 March 2025. "
            "This record tracks the estimated next round. Monitor "
            "https://www.aisi.gov.uk/grants for the official opening date."
        ),
    },
    {
        # ── 2. AISI Alignment Project ─────────────────────────────────────────
        "title":    "AISI Alignment Project",
        "url":      "https://alignmentproject.aisi.gov.uk/",
        "portal":   "https://alignmentproject.aisi.gov.uk/",
        # First cohort selected ~2024-2025; >£15m total (up to £1m per project).
        # Next cohort estimated early 2027.
        "deadline": datetime.date(2027, 2, 1),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Researcher", "Postdoctoral Researcher",
                       "Early Career Researcher", "Mid-Career Researcher",
                       "Senior Researcher"],
        "org_types":  ["University", "Research Institution",
                       "Non-Profit Organisation"],
        "amount_min": None,
        "amount_max": 1000000,
        "currency":   "GBP",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Artificial Intelligence",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The AISI Alignment Project supports research to prevent advanced AI "
            "systems from behaving dangerously — either intentionally or accidentally. "
            "Awards of up to £1 million per project fund new theoretical and empirical "
            "work on developing robust alignment, oversight, and monitoring techniques. "
            "The project is operated as part of AISI's broader mission to facilitate "
            "rigorous research enabling advanced AI governance. The first cohort of "
            "grantees across 60 projects was selected in early 2025, with total funding "
            "exceeding £15 million. "
            "Eligible applicants are researchers at universities, research institutions, "
            "and non-profit organisations worldwide. The programme is administered "
            "through https://alignmentproject.aisi.gov.uk/. "
            "Applications for the first cohort are now closed. This record tracks the "
            "estimated next round. Monitor https://www.aisi.gov.uk/grants for the "
            "official announcement of future cohorts."
        ),
    },
    {
        # ── 3. AISI Systemic Safety Grants ───────────────────────────────────
        "title":    "AISI Systemic Safety Grants",
        "url":      BASE,
        "portal":   PORTAL,
        # First 20 projects selected; underway. Next round estimated mid-2027.
        "deadline": datetime.date(2027, 6, 1),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Researcher", "Postdoctoral Researcher",
                       "Early Career Researcher", "Mid-Career Researcher",
                       "Senior Researcher"],
        "org_types":  ["University", "Research Institution",
                       "Non-Profit Organisation"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "GBP",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Artificial Intelligence", "Public Health", "Energy",
            "Financial Services",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The AISI Systemic AI Safety Grants Programme aims to increase societal "
            "resilience to the widespread deployment of AI across critical sectors "
            "including healthcare, energy grids, and financial markets. The programme "
            "funds research that examines how systemic risks from AI adoption can be "
            "identified, measured, and mitigated at scale. "
            "In the first round, 20 projects were selected; example projects are "
            "documented at https://www.aisi.gov.uk/grants/example-projects. "
            "Applications for the first round are now closed. This record tracks the "
            "estimated next round. Eligible applicants include researchers at "
            "academic institutions and non-profit organisations in the UK and "
            "internationally. Monitor https://www.aisi.gov.uk/grants for the official "
            "announcement of future rounds."
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
    """Advance est by cycle_years until it is in the future."""
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
        "application_deadline_raw":  f"{deadline.day} {deadline.strftime('%B %Y')} (estimated)",
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
    cur.execute("SELECT id FROM grants WHERE source_url = %s AND grant_title = %s",
                (db_rec["source_url"], db_rec["grant_title"]))
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
    parser = argparse.ArgumentParser(description="AISI connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  AI Security Institute — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  AISI: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
