#!/usr/bin/env python3
"""
Burroughs Wellcome Fund (BWF) connector.

The Burroughs Wellcome Fund is a US private foundation (~$50M/year) supporting
biomedical scientists, particularly at early career stages, and areas of science
that are poised for significant advancement but currently undervalued. Awards
are made to degree-granting institutions in the United States and Canada on
behalf of individual researchers.

This connector records two programmes with currently open or imminent
application cycles:

1. Investigators in the Pathogenesis of Infectious Disease (PATH)
   $505,000 over five years; assistant professors; US/CA institutions.
   Annual LOI deadline in mid-July.

2. Career Awards at the Scientific Interface (CASI)
   $560,000 over five years; postdoctoral fellows transitioning from
   physical/computational sciences into biology; US/CA citizens and residents.
   Annual LOI deadline in mid-August.

BWF application portal: https://proposalcentral.com
BWF upcoming deadlines: https://www.bwfund.org/upcoming-deadlines/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/bwf.py [--dry-run]
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

FUNDER  = "Burroughs Wellcome Fund"
DOMAIN  = "api_bwf"
BASE    = "https://www.bwfund.org"
PORTAL  = "https://proposalcentral.com"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── PATH: Investigators in the Pathogenesis of Infectious Disease ────
        "title":    "Investigators in the Pathogenesis of Infectious Disease (PATH)",
        "url":      f"{BASE}/grants/infectious-diseases/investigators-in-the-pathogenesis-of-infectious-disease/",
        "deadline": datetime.date(2026, 7, 16),     # annual LOI deadline
        "open_threshold_days": 75,                   # portal opens ~May each year
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Faculty"],
        "org_types":  ["University", "Research Institution", "Medical School"],
        "amount_min": 505000,
        "amount_max": 505000,
        "currency":   "USD",
        "sectors": [
            "Life Sciences", "Public Health", "Science & Technology",
            "Research & Innovation",
        ],
        "desc": (
            "The Burroughs Wellcome Fund's Investigators in the Pathogenesis of "
            "Infectious Disease (PATH) programme provides opportunities for assistant "
            "professors to bring multidisciplinary approaches to the study of human "
            "infectious diseases. Awards are $505,000 over five years, designed to "
            "give recipients the freedom to pursue new avenues of inquiry and "
            "stimulate higher-risk research that holds the potential to significantly "
            "advance understanding of how infectious diseases work and how health is "
            "maintained. The programme supports research into what happens at the "
            "points where the systems of humans and potentially infectious agents "
            "connect — from molecular interactions to systemic outcomes. "
            "Applicants must hold an appointment at the assistant professor level at "
            "a degree-granting institution in the United States or Canada; the "
            "institution must be a tax-exempt 501(c)(3) organisation. Applications "
            "are submitted through ProposalCentral. A Letter of Intent is required; "
            "those invited on the basis of their LOI then submit a full application. "
            "The annual LOI deadline falls in mid-July."
        ),
    },
    {
        # ── CASI: Career Awards at the Scientific Interface ──────────────────
        "title":    "Career Awards at the Scientific Interface (CASI)",
        "url":      f"{BASE}/grants/interfaces-in-science/career-awards-at-the-scientific-interface/",
        "deadline": datetime.date(2026, 8, 14),     # annual LOI deadline
        "open_threshold_days": 75,                   # portal opens ~June each year
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": 560000,
        "amount_max": 560000,
        "currency":   "USD",
        "sectors": [
            "Science & Technology", "Life Sciences", "Mathematics",
            "Engineering", "Research & Innovation",
        ],
        "desc": (
            "The Burroughs Wellcome Fund's Career Awards at the Scientific Interface "
            "(CASI) provide $560,000 over five years to bridge advanced postdoctoral "
            "training and the first three years of faculty service. Launched in 1999, "
            "CASI fosters early career development for researchers who are "
            "transitioning from training environments in the physical, mathematical, "
            "computational sciences, and/or engineering into postdoctoral work in the "
            "biological sciences, and who are dedicated to pursuing a career in "
            "academic research. "
            "The award is open to U.S. and Canadian citizens, permanent residents, "
            "and temporary residents. Applicants must be in a postdoctoral position "
            "at a degree-granting institution in the United States or Canada; the "
            "institution must be a tax-exempt 501(c)(3) organisation. Applications "
            "are submitted through ProposalCentral. A Letter of Intent is required; "
            "invited applicants then submit a full application. The annual LOI "
            "deadline falls in mid-August."
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
        "application_portal_url":    PORTAL,
        "description":               scheme["desc"],
        "application_deadline":      deadline_iso,
        "application_deadline_raw":  f"{deadline.day} {deadline.strftime('%B %Y')}",
        "grant_opening_date":        opening.isoformat(),
        "current_status":            status,
        "source_language":           "en",
        "funding_amount_min":        scheme["amount_min"],
        "funding_amount_max":        scheme["amount_max"],
        "currency":                  scheme["currency"],
        "thematic_sectors":          scheme["sectors"],
        "grant_types":               scheme["grant_types"],
        "applicant_base_regions":    [],
        "geographic_focus_regions":  ["Global"],
        "applicant_base_countries":  ["US", "CA"],
        "geographic_focus_countries": [],
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
    parser = argparse.ArgumentParser(description="Burroughs Wellcome Fund connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Burroughs Wellcome Fund — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  BWF: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
