#!/usr/bin/env python3
"""
Marsden Fund connector (New Zealand).

The Marsden Fund is New Zealand's premier contestable research fund, managed
by the Marsden Fund Council and administered by Royal Society Te Apārangi on
behalf of the Ministry of Business, Innovation and Employment (MBIE). It
supports excellent investigator-led research across all disciplines —
sciences, engineering, social sciences, and humanities — at New Zealand
universities and research institutes.

Grant types:
  1. Marsden Fund Standard Grant — open to established and emerging researchers
     at NZ institutions. Up to NZD 900,000 over 3 years (average award
     ~NZD 360,000). No restriction on career stage; most applicants hold an
     academic position at a NZ university or Crown Research Institute.
  2. Marsden Fund Fast-Start Grant — reserved for emerging researchers within
     7 years of their PhD conferment. Up to NZD 360,000 over 3 years.
     A separate pool of funds is set aside to encourage early-career applicants.
  3. Marsden Fund Council Award — large interdisciplinary awards supporting
     ambitious collaborative projects across fields. Open to established and
     emerging researchers; amounts are substantially larger than Standard grants.

Application process (two-stage):
  Stage 1: Expression of Interest (EOI) — a 2-page preliminary proposal
    submitted through the Marsden Fund web portal. The annual EOI deadline
    falls in mid-February (noon). Guidelines become available in December.
  Stage 2: Full Proposal — invited applicants (those whose EOIs are
    shortlisted) submit a full application by late June. Full Proposal stage
    is by invitation only.

This connector records three entries — one per grant type — all sharing the
annual EOI deadline (the public-facing entry point). The Full Proposal stage
is not separately listed because it is invitation-only.

Eligibility:
  All applicants must hold a position at a New Zealand-based, Marsden-eligible
  institution (universities, Crown Research Institutes, and certain other
  research bodies). There is no citizenship requirement; international
  researchers employed at eligible NZ institutions may apply.

Timetable source (2026 round, server-rendered):
  https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/marsden/
  marsden-fund-application-process/marsden-fund-timetable

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/marsden_fund.py [--dry-run]
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

FUNDER  = "Marsden Fund (Royal Society Te Apārangi)"
DOMAIN  = "api_marsden"
BASE    = "https://www.royalsociety.org.nz/what-we-do/funds-and-opportunities/marsden"
PORTAL  = f"{BASE}/marsden-fund-application-process/submitting-a-proposal"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. Standard Grant ────────────────────────────────────────────────
        "title":    "Marsden Fund Standard Grant",
        "url":      f"{BASE}/marsden-fund-standard",
        "deadline": datetime.date(2026, 2, 18),     # annual EOI deadline (noon)
        "open_threshold_days": 75,                   # guidelines available ~Dec
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher", "Mid-Career Researcher",
                       "Senior Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 900000,
        "sectors": [
            "Science & Technology", "Life Sciences", "Social Sciences",
            "Humanities", "Engineering", "Research & Innovation",
        ],
        "desc": (
            "The Marsden Fund Standard Grant supports excellent investigator-led "
            "research across all disciplines at New Zealand universities, Crown "
            "Research Institutes, and other Marsden-eligible institutions. Awards "
            "are typically up to NZD 900,000 over three years (average award "
            "approximately NZD 360,000). Both established and emerging researchers "
            "are eligible; there is no restriction on career stage. All principal "
            "investigators must hold a position at a Marsden-eligible New Zealand "
            "institution; there is no New Zealand citizenship or residency "
            "requirement. "
            "Applications proceed in two stages. Stage 1 is a brief Expression of "
            "Interest (EOI) submitted through the Marsden Fund web portal; the "
            "annual EOI deadline falls in mid-February (noon). Applicants whose "
            "EOIs are shortlisted by the Marsden Fund Council are then invited to "
            "submit a Full Proposal by late June. Results are announced in "
            "October–November. The 2027 round EOI deadline is expected in mid-"
            "February 2027; guidelines will be published on the Royal Society Te "
            "Apārangi website from December 2026."
        ),
    },
    {
        # ── 2. Fast-Start Grant ──────────────────────────────────────────────
        "title":    "Marsden Fund Fast-Start Grant",
        "url":      f"{BASE}/marsden-fast-start",
        "deadline": datetime.date(2026, 2, 18),     # same annual EOI deadline
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher", "Postdoctoral Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 360000,
        "sectors": [
            "Science & Technology", "Life Sciences", "Social Sciences",
            "Humanities", "Engineering", "Research & Innovation",
        ],
        "desc": (
            "The Marsden Fund Fast-Start Grant is reserved for emerging researchers "
            "who are within seven years of the conferment of their PhD (excluding "
            "career breaks) and are employed at a Marsden-eligible New Zealand "
            "institution. A dedicated pool of funds is set aside for Fast-Start "
            "applicants to encourage early-career researchers to compete. Awards "
            "are up to NZD 360,000 over three years. "
            "Applications proceed in two stages. Stage 1 is a brief Expression of "
            "Interest (EOI) submitted through the Marsden Fund web portal; the "
            "annual EOI deadline falls in mid-February (noon). Applicants whose "
            "EOIs are shortlisted by the Marsden Fund Council are then invited to "
            "submit a Full Proposal by late June. Results are announced in "
            "October–November. The 2027 round EOI deadline is expected in mid-"
            "February 2027; guidelines will be published on the Royal Society Te "
            "Apārangi website from December 2026. There is no New Zealand "
            "citizenship or residency requirement."
        ),
    },
    {
        # ── 3. Council Award ─────────────────────────────────────────────────
        "title":    "Marsden Fund Council Award",
        "url":      f"{BASE}/marsden-fund-council-award",
        "deadline": datetime.date(2026, 2, 18),     # same annual EOI deadline
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher", "Mid-Career Researcher",
                       "Senior Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "sectors": [
            "Science & Technology", "Life Sciences", "Social Sciences",
            "Humanities", "Engineering", "Research & Innovation",
        ],
        "desc": (
            "The Marsden Fund Council Award is a category introduced to support "
            "large interdisciplinary research projects that would be difficult to "
            "fund through the Standard or Fast-Start grant categories. The award "
            "is open to both established and emerging researchers and supports "
            "ambitious, collaborative work that spans multiple fields. Award "
            "amounts are substantially larger than Standard grants and are "
            "determined by the Marsden Fund Council on a case-by-case basis. "
            "All principal investigators must hold a position at a Marsden-"
            "eligible New Zealand institution. "
            "Applications proceed in two stages: an Expression of Interest (EOI) "
            "submitted in mid-February, followed by an invited Full Proposal in "
            "late June. Results are announced in October–November. The 2027 round "
            "EOI deadline is expected in mid-February 2027; guidelines will be "
            "published from December 2026."
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
        "currency":                  "NZD",
        "thematic_sectors":          scheme["sectors"],
        "grant_types":               scheme["grant_types"],
        "applicant_base_regions":    [],
        "geographic_focus_regions":  [],
        "applicant_base_countries":  ["NZ"],
        "geographic_focus_countries": ["NZ"],
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
    parser = argparse.ArgumentParser(description="Marsden Fund (NZ) connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Marsden Fund — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Marsden Fund: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
