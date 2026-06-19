#!/usr/bin/env python3
"""
The Royal Society connector.

The Royal Society is the UK's national academy of sciences, and the world's
oldest scientific academy in continuous existence. Its grant portfolio funds
researchers across the natural sciences, life sciences, and engineering —
explicitly including biological and biomedical sciences, chemistry,
engineering, mathematics, and physics, but excluding clinical medicine. Most
schemes are restricted to this remit; humanities and social-science
components of jointly run schemes are routed instead to the British Academy.

One scheme, APEX awards, is a deliberate exception: it is run jointly with
the British Academy and the Royal Academy of Engineering (with Leverhulme
Trust support) and explicitly invites applications spanning engineering,
science, and the humanities/social sciences. It is tagged accordingly below
rather than folded into the pure-STEM bucket used for the rest of the
portfolio.

This connector currently represents eight schemes with confirmed, dated
2026/2027 rounds, drawn from the Royal Society's grant-listings search
(https://royalsociety.org/grants/search/grant-listings/) and each scheme's
own detail page. The Royal Society runs roughly 29 schemes in total; the
remainder either have no published forward date at the time of writing
(e.g. Career Development Fellowship, Dorothy Hodgkin Fellowship, Industry
Fellowships, International Exchanges, Research grants) or were not yet
reached via pagination, and can be added in a future pass once dates are
published.

Source: https://royalsociety.org/grants/search/grant-listings/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/royal_society.py [--dry-run]
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

FUNDER = "The Royal Society"
DOMAIN = "api_royal_society"
PORTAL_GENERAL = "https://grants.royalsociety.org/"

STEM_SECTORS = [
    "Physical Sciences", "Life Sciences", "Engineering",
    "Mathematics", "Biomedical Sciences", "Chemistry",
]
ORG_UNI = ["University", "Research Institution"]

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. Entrepreneur in Residence ────────────────────────────────────
        "title":    "Entrepreneur in Residence",
        "url":      "https://royalsociety.org/grants/entrepreneur-in-residence/",
        "portal":   PORTAL_GENERAL,
        "open_date":  datetime.date(2026, 6, 3),
        "deadline":   datetime.date(2026, 8, 19),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 50000,
        "sectors":    ["Physical Sciences", "Life Sciences", "Engineering"],
        "individual": ["Researcher", "Early Career Researcher", "Mid-Career Researcher"],
        "grant_types": ["Fellowship"],
        "desc": (
            "Entrepreneur in Residence provides up to £25,000 per year for up "
            "to two years to support entrepreneurially-minded researchers in "
            "developing the skills and networks needed to translate their "
            "research into real-world impact, working alongside a UK "
            "university or not-for-profit research institution. Eligible "
            "research spans all areas of the life and physical sciences, "
            "including engineering, but excludes clinical medicine. "
            "Decisions are made by 30 November 2026 for the current round."
        ),
    },
    {
        # ── 2. APEX awards (cross-disciplinary exception) ──────────────────
        "title":    "APEX awards",
        "url":      "https://royalsociety.org/grants/apex-awards/",
        "portal":   PORTAL_GENERAL,
        "open_date":  datetime.date(2026, 6, 23),
        "deadline":   datetime.date(2026, 9, 8),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 200000,
        "sectors":    ["Physical Sciences", "Life Sciences", "Engineering",
                       "Social Sciences", "Humanities"],
        "individual": ["Researcher", "Senior Researcher"],
        "grant_types": ["Fellowship", "Award"],
        "desc": (
            "APEX awards provide up to £200,000 to enable established "
            "researchers to pursue genuinely novel, curiosity-driven "
            "projects at the boundary of disciplines. The scheme is run "
            "jointly by the Royal Society, the British Academy, and the "
            "Royal Academy of Engineering, with support from the Leverhulme "
            "Trust, and — unlike most Royal Society schemes — explicitly "
            "welcomes applications spanning engineering, the natural "
            "sciences, and the humanities and social sciences. The 2026 "
            "round opens 23 June 2026, closes 08 September 2026, with "
            "decisions by 30 April 2027."
        ),
    },
    {
        # ── 3. Faraday Discovery Fellowships ────────────────────────────────
        "title":    "Faraday Discovery Fellowships",
        "url":      "https://royalsociety.org/grants/faraday-discovery-fellowships/",
        "portal":   PORTAL_GENERAL,
        "open_date":  datetime.date(2026, 8, 5),
        "deadline":   datetime.date(2026, 9, 22),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 8000000,
        "sectors":    STEM_SECTORS,
        "individual": ["Researcher", "Senior Researcher"],
        "grant_types": ["Fellowship"],
        "desc": (
            "Faraday Discovery Fellowships offer up to £8 million over 10 "
            "years to support outstanding researchers pursuing ambitious, "
            "long-term discovery science. Eligible fields are restricted to "
            "the natural sciences: biological research and biomedical "
            "sciences, chemistry, engineering, mathematics, and physics. "
            "The 2027 Stage 1 round opens 05 August 2026, closes 22 "
            "September 2026, with Stage 1 decisions by 30 November 2026 "
            "ahead of an invitation-only Stage 2."
        ),
    },
    {
        # ── 4. Newton International Fellowships ─────────────────────────────
        "title":    "Newton International Fellowships",
        "url":      "https://royalsociety.org/grants/newton-international/",
        "portal":   PORTAL_GENERAL,
        "open_date":  datetime.date(2026, 1, 15),
        "deadline":   datetime.date(2026, 3, 11),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 280000,
        "sectors":    STEM_SECTORS,
        "individual": ["Postdoctoral Researcher", "Early Career Researcher"],
        "grant_types": ["Fellowship"],
        "desc": (
            "Newton International Fellowships provide up to £280,000 over "
            "two years to support early-career postdoctoral researchers "
            "from overseas to work at a UK research institution. The "
            "scheme is restricted to the Royal Society's natural-science "
            "remit — biological and biomedical sciences, chemistry, "
            "engineering, mathematics, and physics — and explicitly "
            "excludes humanities and social sciences, which are supported "
            "instead through the parallel British Academy scheme of the "
            "same name. The most recent round opened 15 January 2026 and "
            "closed 11 March 2026, with decisions by 31 August 2026; this "
            "record advances automatically to the next annual cycle once "
            "the current round closes."
        ),
    },
    {
        # ── 5. Royal Society Wolfson Fellowship ─────────────────────────────
        "title":    "Royal Society Wolfson Fellowship",
        "url":      "https://royalsociety.org/grants/royal-society-wolfson-fellowship/",
        "portal":   PORTAL_GENERAL,
        "open_date":  datetime.date(2026, 5, 6),
        "deadline":   datetime.date(2026, 7, 1),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 300000,
        "sectors":    STEM_SECTORS,
        "individual": ["Mid-Career Researcher", "Senior Researcher"],
        "grant_types": ["Fellowship"],
        "desc": (
            "The five-year Royal Society Wolfson Fellowship, jointly funded "
            "with the Wolfson Foundation, provides up to £300,000 to enable "
            "UK universities and not-for-profit research institutions to "
            "recruit outstanding emerging or established international "
            "research leaders relocating to the UK. Funds can cover salary "
            "enhancement, research expenses, research assistance, PhD "
            "studentships, and relocation/visa costs. Eligible research "
            "falls within the Royal Society's natural-sciences remit. "
            "Candidates must be nominated by their host institution. The "
            "2026 round 2 opens 06 May 2026, closes 01 July 2026, with "
            "decisions by 30 November 2026."
        ),
    },
    {
        # ── 6. Royal Society Wolfson Visiting Fellowship ────────────────────
        "title":    "Royal Society Wolfson Visiting Fellowship",
        "url":      "https://royalsociety.org/grants/royal-society-wolfson-visiting-fellowship/",
        "portal":   PORTAL_GENERAL,
        "open_date":  datetime.date(2026, 5, 6),
        "deadline":   datetime.date(2026, 7, 1),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 125000,
        "sectors":    STEM_SECTORS,
        "individual": ["Senior Researcher"],
        "grant_types": ["Fellowship"],
        "desc": (
            "The Royal Society Wolfson Visiting Fellowship, jointly funded "
            "with the Wolfson Foundation, provides up to £125,000 for "
            "outstanding international research leaders to undertake a "
            "flexible 12-month period of sabbatical leave (full-time, or "
            "spread over 24 months) at a UK university or not-for-profit "
            "research institution, fostering collaborative research links. "
            "Eligible research falls within the Royal Society's "
            "natural-sciences remit. Candidates must be nominated by their "
            "host institution. The 2026 round 2 opens 06 May 2026, closes "
            "01 July 2026, with decisions by 30 November 2026."
        ),
    },
    {
        # ── 7. Policy Associate scheme ───────────────────────────────────────
        "title":    "Policy Associate scheme",
        "url":      "https://royalsociety.org/grants/training-mentoring-partnership-schemes/science-policy-associate-scheme/",
        "portal":   "https://grants.royalsociety.org/startapplication.aspx?id=2283",
        "open_date":  datetime.date(2026, 5, 5),
        "deadline":   datetime.date(2026, 7, 9),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Science & Technology", "Policy & Governance"],
        "individual": ["Postdoctoral Researcher", "Early Career Researcher"],
        "grant_types": ["Fellowship"],
        "desc": (
            "The Policy Associate scheme funds a 3-month full-time (or "
            "6-9 month part-time equivalent) secondment for current Royal "
            "Society University Research Fellows, Dorothy Hodgkin Fellows, "
            "and Career Development Fellows into a science policy "
            "environment — a government department, devolved "
            "administration, arm's-length body, or other relevant public "
            "organisation — to gain first-hand experience of how research "
            "informs decision-making. Applicants must have completed the "
            "first year of their fellowship by July 2026 with at least 18 "
            "months remaining. The 2026 round opens 05 May 2026, closes "
            "09 July 2026, with a decision by 01 September 2026."
        ),
    },
    {
        # ── 8. Partnership Grants ────────────────────────────────────────────
        "title":    "Partnership Grants",
        "url":      "https://royalsociety.org/grants/partnership-grants/",
        "portal":   "https://grants.royalsociety.org/",
        "open_date":  datetime.date(2026, 2, 23),
        "deadline":   datetime.date(2026, 12, 1),
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": 3000,
        "sectors":    ["Education & Schools", "Science & Technology"],
        "individual": [],
        "grant_types": ["Project Grant"],
        "org_types":   ["School", "College"],
        "desc": (
            "Partnership Grants fund UK schools and colleges up to £3,000 "
            "to work in partnership with a STEM professional from academia "
            "or industry to run an investigative STEM project, open to "
            "students aged 5-18. The 2026 round runs to three submission "
            "deadlines (30 April, 10 July, and 30 November 2026), closing "
            "01 December 2026; a linked Tomorrow's Climate Scientists "
            "extension specifically funds climate-change and biodiversity "
            "projects. Schools and colleges outside the UK (excluding the "
            "Channel Islands and Isle of Man) are not eligible."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_UNI)
    _s.setdefault("currency", "GBP")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", ["United Kingdom"])
    _s.setdefault("focus_countries", ["United Kingdom"])
    # open_threshold_days = the scheme's own observed open-to-close window
    _s.setdefault(
        "open_threshold_days",
        (_s["deadline"] - _s["open_date"]).days,
    )


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
# even though every Royal Society scheme here has a unique source_url)
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
    parser = argparse.ArgumentParser(description="Royal Society connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  The Royal Society — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Royal Society: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
