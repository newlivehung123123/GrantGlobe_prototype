#!/usr/bin/env python3
"""
The Russell Sage Foundation (RSF) connector.

RSF is a New York-based foundation dedicated exclusively to strengthening the
methods, data, and theoretical core of the social sciences in order to
improve social and living conditions in the United States. All of its
research grant programs require a doctorate (or, for the Dissertation
Research Grants, near-completion of one) and are scoped to US-relevant
social-science research; RSF explicitly does not fund health, mental-health,
or routine-use-of-public-data projects.

This connector represents six current, dated programs drawn directly from
RSF's own application pages: Core Research Grants (the foundation's flagship,
~$200K, LOI-gated program, currently accepting LOIs only under its
Behavioral Science and Decision Making in Context / Race, Ethnicity, and
Immigration / Immigration and Immigrant Integration / Race-Conscious
Admissions Ban tracks — the Social, Political and Economic Inequality and
Future of Work tracks are explicitly not accepting applications at the time
of writing), the Sheldon Danziger Pipeline Grants for early-career scholars,
Dissertation Research Grants, the Causal Research on the Criminal Justice
System program (run jointly with Arnold Ventures), and the Visiting
Scholars / Visiting Researchers residential fellowships.

The Fluxx application portal foundation-wide opens exactly two months ahead
of each deadline (stated verbatim on RSF's Application Deadlines page); this
is used as a shared, sourced "open_threshold_days" of 60 across all schemes
below, rather than a guessed or per-scheme estimate.

Source: https://www.russellsage.org/apply/application-deadlines
        https://www.russellsage.org/apply/info

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/russell_sage.py [--dry-run]
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

FUNDER = "Russell Sage Foundation"
DOMAIN = "api_russell_sage"
PORTAL_GENERAL = "https://rsf.fluxx.io/"

SOCIAL_SCIENCE_SECTORS = [
    "Behavioral Science", "Race, Ethnicity & Immigration",
    "Social, Political & Economic Inequality", "Future of Work",
]
ORG_UNI = ["University", "Research Institution"]

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. Core Research Grants ─────────────────────────────────────────
        "title":    "Core Research Grants",
        "url":      "https://www.russellsage.org/apply/grants/core",
        "portal":   "https://rsf.fluxx.io/user_sessions/new",
        "deadline":   datetime.date(2026, 7, 15),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 200000,
        "sectors":    SOCIAL_SCIENCE_SECTORS,
        "individual": ["Researcher", "Postdoctoral Researcher", "Senior Researcher"],
        "grant_types": ["Research Grant"],
        "desc": (
            "Core Research Grants provide up to $200,000 (including 15% "
            "indirect costs on grants over $75,000) for PhD holders to "
            "conduct research aligned with RSF's priority areas. All "
            "applications must be preceded by a letter of inquiry (max 4 "
            "single-spaced pages); after peer review, roughly 15% of LOI "
            "submitters are invited to submit a full proposal, with a final "
            "funding rate of approximately 6-10% of LOIs. RSF rarely "
            "considers projects whose research design, sample framework, "
            "and data access are not already fully developed. The LOI "
            "deadline of 15 July 2026 (2pm ET) covers the Behavioral Science "
            "and Decision Making in Context, Race, Ethnicity, and "
            "Immigration, Immigration and Immigrant Integration, and "
            "Race-Conscious College Admissions Ban tracks; the Social, "
            "Political and Economic Inequality and Future of Work tracks "
            "are not currently accepting applications. Decisions are "
            "expected by March 2027 for grants starting on or after 1 May "
            "2027."
        ),
    },
    {
        # ── 2. Sheldon Danziger Pipeline Grants ─────────────────────────────
        "title":    "Sheldon Danziger Pipeline Grants",
        "url":      "https://www.russellsage.org/apply/grants/pipeline",
        "portal":   PORTAL_GENERAL,
        "deadline":   datetime.date(2026, 10, 21),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 65000,
        "sectors":    ["Economic Mobility", "Social, Political & Economic Inequality"],
        "individual": ["Assistant Professor", "Early Career Researcher"],
        "grant_types": ["Research Grant"],
        "desc": (
            "The Sheldon Danziger Pipeline Grants (renamed in 2025; formerly "
            "co-funded with the Bill & Melinda Gates Foundation) support "
            "early-career scholars — assistant professors, lecturers, and "
            "adjunct professors — researching economic mobility and access "
            "to opportunity in the United States, with a priority on "
            "applicants underrepresented in the social sciences and/or "
            "employed at under-resourced colleges and universities. Grants "
            "of up to $65,000 fund one-year, investigator-initiated "
            "projects; only faculty who have not previously received RSF "
            "research support or a visiting fellowship are eligible. "
            "Grantees are paired with senior-scholar mentors. The next "
            "deadline is 21 October 2026 (2pm ET), for funding starting "
            "Summer 2027."
        ),
    },
    {
        # ── 3. Dissertation Research Grants ─────────────────────────────────
        "title":    "Dissertation Research Grants",
        "url":      "https://www.russellsage.org/apply/grants/dissertation",
        "portal":   "https://rsf.fluxx.io/user_sessions/new",
        "deadline":   datetime.date(2026, 2, 3),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 15000,
        "sectors":    [
            "Behavioral Science", "Future of Work", "Race, Ethnicity & Immigration",
            "Immigration & Immigrant Integration", "Social, Political & Economic Inequality",
        ],
        "individual": ["Doctoral Student"],
        "grant_types": ["Dissertation Grant"],
        "org_types": ["University"],
        "desc": (
            "Dissertation Research Grants provide $15,000 to enrolled "
            "doctoral students at a US institution of higher education who "
            "have completed all program requirements except the "
            "dissertation, to support data collection, preparation, "
            "analysis, and writing. There is a lifetime limit of one award "
            "per applicant, and previous RSF grant recipients are "
            "ineligible. RSF expects to approve up to 20 grants per cycle "
            "and prioritizes applicants who lack sufficient funding or time "
            "for the dissertation; fully-funded applicants on a "
            "departmental, university, or national fellowship are unlikely "
            "to be externally reviewed. Decisions are announced in May, "
            "with grants starting on or after 1 July. The most recently "
            "published deadline was 3 February 2026 (2pm ET); this record "
            "advances automatically to the foundation's announced next "
            "cycle of February 2027."
        ),
    },
    {
        # ── 4. Causal Research on the Criminal Justice System ──────────────
        "title":    "Causal Research on the Criminal Justice System",
        "url":      "https://www.russellsage.org/apply/grants/causal-research-criminal-justice",
        "portal":   PORTAL_GENERAL,
        "deadline":   datetime.date(2026, 4, 1),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 100000,
        "sectors":    ["Criminal Justice", "Race, Ethnicity & Immigration",
                       "Social, Political & Economic Inequality"],
        "individual": ["Assistant Professor", "Early Career Researcher"],
        "grant_types": ["Research Grant"],
        "desc": (
            "Run jointly with the Criminal Justice program at Arnold "
            "Ventures, this competition funds early-career, tenure-track "
            "assistant professors at a US college or university to "
            "conduct causal research (e.g. difference-in-differences, "
            "regression discontinuity, instrumental variables, randomized "
            "controlled trials) on policing, courts, jails, prisons, "
            "probation/parole, or immigration detention. Grants of up to "
            "$100,000 (including 15% indirect costs) fund one-year "
            "projects; grantees are paired with senior-scholar mentors and "
            "present findings at a research conference. The most recent "
            "round's deadline was 1 April 2026 (2pm ET) for funding "
            "starting 1 October 2026; this record advances automatically to "
            "the foundation's announced next cycle of April 2027."
        ),
    },
    {
        # ── 5. Visiting Scholars ─────────────────────────────────────────────
        "title":    "Visiting Scholars",
        "url":      "https://www.russellsage.org/apply/visiting-scholar",
        "portal":   "https://rsf.fluxx.io/user_sessions/new",
        "deadline":   datetime.date(2026, 6, 25),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 150000,
        "sectors":    SOCIAL_SCIENCE_SECTORS,
        "individual": ["Senior Researcher", "Researcher"],
        "grant_types": ["Fellowship"],
        "org_types": [],
        "desc": (
            "The Visiting Scholars Program funds a residential fellowship "
            "at RSF's New York City headquarters, either a 10-month term "
            "(September-June) or a 5-month half-year term, for scholars in "
            "the social, economic, political, and behavioral sciences who "
            "are at least two years beyond the PhD. Scholars receive an "
            "office, research resources, and salary support of typically up "
            "to 50% of academic-year salary (maximum $150,000 for a full "
            "year or $75,000 for a half year), plus partially subsidized "
            "housing for those relocating from outside the New York area; "
            "15-17 fellowships are awarded annually. Applications, due 25 "
            "June 2026 (2pm ET) for the September 2027-June 2028 residency "
            "year, require a 5-page proposal and an abbreviated CV."
        ),
    },
    {
        # ── 6. Visiting Researcher ───────────────────────────────────────────
        "title":    "Visiting Researcher",
        "url":      "https://www.russellsage.org/apply/visiting-researcher",
        "portal":   PORTAL_GENERAL,
        "deadline":   datetime.date(2027, 5, 4),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors":    [],
        "individual": ["Researcher"],
        "grant_types": ["Fellowship"],
        "org_types": [],
        "desc": (
            "On an occasional, space-available basis, RSF offers short-term "
            "residential fellowships (up to five months, between 1 "
            "September and 30 June, with visits up to ten months "
            "considered in rare circumstances) to scholars conducting "
            "research relevant to the foundation's priority areas. Unlike "
            "the Visiting Scholars Program, this fellowship carries no "
            "financial support — only an office, computer, software, and "
            "access to research materials, plus partially subsidized "
            "housing where available for those relocating from outside the "
            "New York area. The next published deadline is 4 May 2027 (2pm "
            "ET), for residency between September 2027 and June 2028."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_UNI)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", ["United States"])
    _s.setdefault("focus_countries", ["United States"])
    # The Fluxx portal opens exactly two months (60 days) ahead of every
    # deadline foundation-wide, per RSF's own Application Deadlines page.
    _s.setdefault("open_threshold_days", 60)

# Dissertation Research Grants and the Causal Research on the Criminal
# Justice System program both explicitly require a US institutional base.
for _title in ("Dissertation Research Grants", "Causal Research on the Criminal Justice System"):
    next(s for s in SCHEMES if s["title"] == _title)["applicant_countries"] = ["United States"]


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
        "application_deadline_raw":  deadline.strftime("%d %B %Y"),
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
# DB upsert (composite key: source_url + grant_title — defensive convention
# even though every Russell Sage scheme here has a unique source_url)
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    db_rec = {k: v for k, v in record.items() if not k.startswith("_")}
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s AND grant_title = %s",
                (db_rec["source_url"], db_rec["grant_title"]))
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
    parser = argparse.ArgumentParser(description="Russell Sage Foundation connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Russell Sage Foundation — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Russell Sage Foundation: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
