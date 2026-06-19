#!/usr/bin/env python3
"""
Howard Hughes Medical Institute (HHMI) connector.

HHMI is one of the largest private biomedical research funders in the United States,
disbursing approximately $1 billion per year to support fundamental research in the
biological and biomedical sciences. Unlike most funders, HHMI supports scientists
directly as employees rather than funding specific projects, reflecting its philosophy
of backing "people, not projects."

All HHMI competitions are restricted to researchers at HHMI-eligible institutions
(primarily US research universities and medical schools). Applicants may be of any
nationality provided they are authorised to work in the United States.

Schemes covered (4 programs, all static — deadlines are published well in advance):

  1. Gilliam Fellows Program (PhD)
       Annual competition for second- and third-year PhD students and their advisors.
       Applications open Sep 1, 2026; close Oct 27, 2026.

  2. Hanna H. Gray Fellows Program (Postdoc → Faculty transition)
       Biennial competition for postdoctoral scientists (≤7 years post-PhD).
       From 2028, combined with the Freeman Hrabowski Scholars competition.
       Applications open Nov 3, 2026; close Dec 15, 2026.

  3. Freeman Hrabowski Scholars Program (Early Career Faculty)
       Biennial competition for early career faculty (≤7 years as lab head).
       From 2028, combined with the Hanna H. Gray Fellows competition.
       Applications open Nov 3, 2026; close Dec 15, 2026.

  4. HHMI Investigator Program (Mid-Career & Senior Faculty)
       Five-yearly competition for established faculty (≥7 years as lab head).
       Next competition opens late 2027; deadline estimated ~Jan 2028.

Live fetching:
  HHMI program pages (hhmi.org/programs/*) are server-rendered (Drupal 10) and
  state application dates in a "Program Snapshot" sidebar. However, the dates
  change only at competition boundaries (annually or biennially), and the next
  cycle's dates are already published, so this connector uses static dates rather
  than live fetching. Dates are confirmed from the live pages as of June 2026.

  When a competition deadline passes, _advance_deadline() advances the estimate
  by the appropriate cycle length (1, 2, or 5 years) so the connector remains
  correct across re-runs without code changes.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/hhmi.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
from pathlib import Path

import psycopg2

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FUNDER = "Howard Hughes Medical Institute (HHMI)"
DOMAIN = "api_hhmi"
PORTAL = "https://arc.hhmi.org/"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------
# Each scheme dict:
#   title                 – grant title (used as DB key via source_url)
#   url                   – canonical program page
#   deadline              – application close date for next known competition
#   open_threshold_days   – number of days before deadline on which status → "Open"
#                           (set to the interval between the open and close dates)
#   cycle_years           – how often the competition repeats (for auto-advance)
#   individual            – individual_eligibility tags
#   sectors               – thematic_sectors tags
#   desc                  – long description

SCHEMES: list[dict] = [
    {
        "title":   "HHMI Gilliam Fellows Program",
        "url":     "https://www.hhmi.org/programs/gilliam-fellows",
        "deadline": datetime.date(2026, 10, 27),   # closes Oct 27 2026
        "open_threshold_days": 56,                  # opens Sep 1 (56 days before)
        "cycle_years": 1,                           # annual competition
        "individual": ["PhD Student"],
        "sectors": [
            "Life Sciences", "Biomedical Research",
            "Research & Innovation",
        ],
        "desc": (
            "The HHMI Gilliam Fellows Program is an annual competition that supports "
            "second- and third-year PhD students in the basic biological and biomedical "
            "sciences and their faculty PhD advisors at HHMI-eligible US institutions. "
            "It is unique in funding mentor–mentee pairs simultaneously. Fellows receive "
            "up to three years of stipend support, a discretionary allowance, and an "
            "institutional allowance for tuition and fees during their PhD, together "
            "with tailored professional development programming for both student and "
            "advisor. Gilliam PhD Fellows interested in academic research careers may "
            "subsequently apply for four additional years of postdoctoral support as "
            "Gilliam Postdoc Fellows. No nomination is required; applications are "
            "submitted through HHMI's Application and Review Channel (ARC) and are "
            "open to US citizens, permanent residents, DACA recipients, and "
            "international students who are eligible to study and receive funding at "
            "their graduate institution. The 2027 competition opens September 1, 2026 "
            "and closes October 27, 2026."
        ),
    },
    {
        "title":   "HHMI Hanna H. Gray Fellows Program",
        "url":     "https://www.hhmi.org/programs/hanna-h-gray-fellows",
        "deadline": datetime.date(2026, 12, 15),   # closes Dec 15 2026
        "open_threshold_days": 42,                  # opens Nov 3 (42 days before)
        "cycle_years": 2,                           # biennial competition
        "individual": ["Postdoctoral Researcher"],
        "sectors": [
            "Life Sciences", "Biomedical Research",
            "Research & Innovation",
        ],
        "desc": (
            "The HHMI Hanna H. Gray Fellows Program is a biennial competition that "
            "supports postdoctoral scientists with no more than seven years of "
            "postdoctoral experience who show exceptional promise as future independent "
            "research leaders in the basic biological and biomedical sciences. "
            "Fellows receive up to two years of salary or stipend support commensurate "
            "with experience, additional support for fellowship-associated expenses, "
            "personalised career transition support for the faculty job search, and "
            "professional development through workshops, retreats, and HHMI Science "
            "Meetings. The Fellowship provides a direct pathway to the Freeman "
            "Hrabowski Scholars Program: Fellows who obtain a qualifying tenure-track "
            "or equivalent faculty position at an HHMI-eligible institution are "
            "appointed as Scholars if other program requirements are met. Beginning "
            "with the 2028 competition, the Hanna H. Gray Fellows and Freeman "
            "Hrabowski Scholars Programs select scientists through a single combined "
            "competition, with review specific to career stage. Applicants must be "
            "authorised to work in the US or eligible to obtain work authorisation "
            "for the duration of the appointment. The 2028 competition opens "
            "November 3, 2026 and closes December 15, 2026."
        ),
    },
    {
        "title":   "HHMI Freeman Hrabowski Scholars Program",
        "url":     "https://www.hhmi.org/programs/freeman-hrabowski-scholars",
        "deadline": datetime.date(2026, 12, 15),   # closes Dec 15 2026
        "open_threshold_days": 42,                  # opens Nov 3 (42 days before)
        "cycle_years": 2,                           # biennial competition
        "individual": ["Early Career Faculty"],
        "sectors": [
            "Life Sciences", "Biomedical Research",
            "Research & Innovation",
        ],
        "desc": (
            "The HHMI Freeman Hrabowski Scholars Program is a biennial competition "
            "that supports outstanding early career tenured and tenure-track faculty "
            "— including physician-scientists — with at most seven years of experience "
            "directing a lab at an HHMI-eligible US institution. Scholars become HHMI "
            "employees while maintaining their academic appointments and receive full "
            "salary and benefits, a generous annual research budget, access to HHMI's "
            "capital equipment program, and tailored professional development including "
            "a year-long Science Leadership & Lab Culture course. The initial term is "
            "five years, renewable for a second five-year term following a successful "
            "midpoint evaluation. Beginning with the 2028 competition, the Freeman "
            "Hrabowski Scholars and Hanna H. Gray Fellows Programs select scientists "
            "through a single combined competition, with applicant review specific to "
            "career stage; Hanna Gray postdoctoral scientists who subsequently obtain "
            "a qualifying faculty position are appointed as Scholars. Applicants must "
            "be authorised to work in the US or eligible to obtain work authorisation "
            "for the duration of the appointment. The 2028 competition opens "
            "November 3, 2026 and closes December 15, 2026."
        ),
    },
    {
        "title":   "HHMI Investigator Program",
        "url":     "https://www.hhmi.org/programs/investigators",
        "deadline": datetime.date(2028, 1, 15),    # estimated; competition opens late 2027
        "open_threshold_days": 90,
        "cycle_years": 5,                           # quinquennial competition
        "individual": ["Mid-Career Faculty", "Senior Faculty"],
        "sectors": [
            "Life Sciences", "Biomedical Research",
            "Research & Innovation",
        ],
        "desc": (
            "The HHMI Investigator Program provides generous, long-term support to "
            "established mid-career and senior faculty — including physician-scientists "
            "— who are conducting fundamental research in the biological and biomedical "
            "sciences at HHMI-eligible US institutions. Eligibility requires at least "
            "seven years of experience as a lab head; there is no upper career-stage "
            "limit. Investigators are appointed as HHMI employees for seven-year "
            "renewable terms and receive their full salary and benefits from the "
            "Institute while maintaining academic appointments and laboratories at "
            "their home institution, along with substantial research support and "
            "access to a capital equipment fund. More than 30 current or emeriti "
            "HHMI Investigators have been awarded Nobel Prizes. The competition runs "
            "every five years; the most recent competition concluded in 2022–23 "
            "and the next competition is expected to open in late 2027, with a "
            "deadline estimated in early 2028."
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
        except ValueError:  # Feb 29 edge case
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
    open_thr = scheme["open_threshold_days"]

    if days_until < 0:
        status = "Closed"
    elif days_until <= open_thr:
        status = "Open"
    else:
        status = "Forthcoming"

    opening = deadline - datetime.timedelta(days=open_thr)
    deadline_iso = deadline.isoformat()

    return {
        "grant_title":              scheme["title"],
        "funder_name":              FUNDER,
        "source_url":               scheme["url"],
        "application_portal_url":   PORTAL,
        "description":              scheme["desc"],
        "application_deadline":     deadline_iso,
        "application_deadline_raw": f"{deadline.day} {deadline.strftime('%B %Y')}",
        "grant_opening_date":       opening.isoformat(),
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 "USD",
        "thematic_sectors":         scheme["sectors"],
        "grant_types":              ["Fellowship", "Research Grant"],
        "applicant_base_regions":   [],
        "geographic_focus_regions": [],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": ["US"],
        "organisation_types":       ["University", "Research Institution",
                                     "Medical School"],
        "individual_eligibility":   scheme["individual"],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(
                                        scheme["url"], scheme["title"], deadline_iso
                                    ),
        # carry-along for dry-run display only
        "_days_until":  days_until,
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    """Insert or update by source_url. Returns 'inserted' or 'updated'."""
    # Strip internal keys before touching the DB
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
                crawl_date = %s, content_hash = %s
               WHERE id = %s""",
            (
                db_rec["grant_title"], db_rec["description"],
                db_rec["application_deadline"], db_rec["application_deadline_raw"],
                db_rec["grant_opening_date"], db_rec["current_status"],
                db_rec["crawl_date"], db_rec["content_hash"],
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
    parser = argparse.ArgumentParser(description="HHMI connector for GrantGlobe")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    # Always print a summary
    print(f"\n{'─'*65}")
    print(f"  HHMI — {len(records)} schemes  (today: {today})")
    print(f"{'─'*65}")
    for rec in records:
        print(
            f"  [{rec['current_status']:<13}] {rec['grant_title']:<47} "
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
    print(f"\n  HHMI: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
