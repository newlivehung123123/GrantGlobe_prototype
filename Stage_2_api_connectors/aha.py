#!/usr/bin/env python3
"""
American Heart Association (AHA) connector.

The American Heart Association is the largest non-profit, non-governmental
funder of cardiovascular and cerebrovascular research in the United States,
having invested more than $6.1 billion in research since 1949. It funds
basic, clinical, population, and data science research through annual and
one-time grant programmes. Applications are submitted through ProposalCentral.

This connector records five annually recurring open-topic programmes:

1. Predoctoral Fellowship
   Supports promising students in pre-doctoral or clinical health professional
   degree programmes intending research careers. Deadline: ~August 4.

2. Postdoctoral Fellowship
   Supports postdoctoral applicants who are not yet independent researchers,
   embedded in a mentored investigative group. Deadline: ~August 5.

3. Institutional Award for Undergraduate Student Training
   Awarded to qualified institutions to provide meaningful cardiovascular
   research experiences to undergraduate students. Deadline: ~September 9.

4. Institutional Research Enhancement Award (AIREA)
   Stimulates research at institutions that have not been major recipients
   of NIH support; enhances student exposure to research. Deadline: ~September 10.

5. Career Development Award
   Supports highly promising early-career healthcare and academic professionals
   to establish independent research careers. Deadline: ~December 1.

Source: https://professional.heart.org/en/research-programs/aha-funding-opportunities
Portal: https://proposalcentral.com

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/aha.py [--dry-run]
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

FUNDER  = "American Heart Association"
DOMAIN  = "api_aha"
BASE    = "https://professional.heart.org/en/research-programs/aha-funding-opportunities"
PORTAL  = "https://proposalcentral.com"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. Predoctoral Fellowship ─────────────────────────────────────────
        "title":    "AHA Predoctoral Fellowship",
        "url":      f"{BASE}/predoctoral-fellowship",
        "deadline": datetime.date(2026, 8, 4),       # annual deadline
        "open_threshold_days": 180,                   # AHA opens programs ~6 months ahead
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Graduate Student"],
        "org_types":  ["University", "Medical School", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Life Sciences", "Public Health", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": ["US"],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The American Heart Association Predoctoral Fellowship enhances the "
            "training of promising students who are enrolled in pre-doctoral or "
            "clinical health professional degree training programmes and who intend "
            "careers as scientists, physician-scientists, clinician-scientists, or "
            "related health research careers aimed at improving global cardiovascular "
            "and cerebrovascular health. "
            "Applicants must be enrolled full-time in an accredited degree programme "
            "at a US institution, be a citizen, permanent resident, or non-citizen "
            "national of the US (or an international student at a US institution for "
            "certain sub-award categories), and have a faculty mentor who holds an "
            "AHA-eligible appointment. The award provides salary support, tuition, "
            "and research expenses. Duration is one to three years. "
            "Within this programme, dedicated collaboration funding is available "
            "through partnerships with the Children's Heart Foundation (congenital "
            "heart defects), Autism Speaks, the Barth Syndrome Foundation, the "
            "California Walnut Commission, and the Foundation for Sarcoidosis "
            "Research. Applications are submitted through ProposalCentral. The "
            "annual proposal deadline falls in early August."
        ),
    },
    {
        # ── 2. Postdoctoral Fellowship ────────────────────────────────────────
        "title":    "AHA Postdoctoral Fellowship",
        "url":      f"{BASE}/postdoctoral-fellowship",
        "deadline": datetime.date(2026, 8, 5),       # annual deadline
        "open_threshold_days": 180,
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  ["University", "Medical School", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Life Sciences", "Public Health", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": ["US"],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The American Heart Association Postdoctoral Fellowship enhances the "
            "training of postdoctoral applicants who are not yet independent "
            "investigators. The applicant must be embedded in an appropriate "
            "investigative group under the mentorship, support, and scientific "
            "guidance of a research mentor. The fellowship supports cardiovascular "
            "and cerebrovascular basic, clinical, population, and data science "
            "research. "
            "Applicants must hold a doctoral degree (MD, PhD, or equivalent) and "
            "be in an active postdoctoral training position at a US institution at "
            "the time of application. Citizenship restrictions apply depending on "
            "the applicable sub-award collaboration. Duration is one to three years. "
            "Dedicated collaboration funding is also available through partnerships "
            "with the Children's Heart Foundation, Autism Speaks, the Barth Syndrome "
            "Foundation, the California Walnut Commission, the Foundation for "
            "Sarcoidosis Research, the Pulmonary Hypertension Association, and the "
            "VIVA Foundation. Applications are submitted through ProposalCentral. "
            "The annual proposal deadline falls in early August."
        ),
    },
    {
        # ── 3. Institutional Award for Undergraduate Student Training ─────────
        "title":    "AHA Institutional Award for Undergraduate Student Training",
        "url":      f"{BASE}/institutional-award-for-undergraduate-student-training",
        "deadline": datetime.date(2026, 9, 9),       # annual deadline
        "open_threshold_days": 180,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": [],
        "org_types":  ["University", "College"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Life Sciences", "Public Health", "Science & Technology",
            "Research & Innovation", "Education",
        ],
        "applicant_countries": ["US"],
        "focus_regions":       [],
        "focus_countries":     [],
        "desc": (
            "The American Heart Association Institutional Award for Undergraduate "
            "Student Training is made to qualified research institutions that can "
            "offer a meaningful cardiovascular and cerebrovascular research experience "
            "to undergraduate college students from all disciplines, encouraging them "
            "to consider research careers. The award is made to the institution (not "
            "to individual students), which then selects and supports trainees under "
            "the programme. "
            "Eligible applicant institutions must be accredited colleges or "
            "universities in the United States. Applications are submitted through "
            "ProposalCentral by the institution. The annual proposal deadline falls "
            "in early September."
        ),
    },
    {
        # ── 4. AHA Institutional Research Enhancement Award (AIREA) ──────────
        "title":    "AHA Institutional Research Enhancement Award (AIREA)",
        "url":      f"{BASE}/aha-institutional-research-enhancement-award-airea",
        "deadline": datetime.date(2026, 9, 10),      # annual deadline
        "open_threshold_days": 180,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": [],
        "org_types":  ["University", "College", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Life Sciences", "Public Health", "Science & Technology",
            "Research & Innovation", "Education",
        ],
        "applicant_countries": ["US"],
        "focus_regions":       [],
        "focus_countries":     [],
        "desc": (
            "The American Heart Association Institutional Research Enhancement Award "
            "(AIREA) stimulates cardiovascular and cerebrovascular research at "
            "educational institutions that provide baccalaureate or advanced degrees "
            "related to scientific research training, but that have not been major "
            "recipients of NIH support. "
            "Eligible institutions include accredited US academic institutions that "
            "award baccalaureate or advanced degrees and have not been significant "
            "recipients of NIH research funding. Awards fund small-scale research "
            "projects, enhance the research environment at eligible institutions, "
            "and expose students to research opportunities in cardiovascular science. "
            "Applications are submitted by the institution through ProposalCentral. "
            "The annual proposal deadline falls in early September."
        ),
    },
    {
        # ── 5. Career Development Award ───────────────────────────────────────
        "title":    "AHA Career Development Award",
        "url":      f"{BASE}/career-development-award",
        "deadline": datetime.date(2026, 12, 1),      # annual deadline
        "open_threshold_days": 180,
        "cycle_years": 1,
        "grant_types": ["Research Grant", "Fellowship"],
        "individual": ["Early Career Faculty", "Early Career Researcher"],
        "org_types":  ["University", "Medical School", "Research Institution",
                       "Hospital"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Life Sciences", "Public Health", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": ["US"],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The American Heart Association Career Development Award supports highly "
            "promising healthcare and academic professionals in the early years of "
            "their first professional appointment to assure future success as "
            "research scientists in cardiovascular and cerebrovascular disease "
            "research. The award is designed to help early-career investigators "
            "build the track record needed for subsequent peer-reviewed funding. "
            "Applicants must hold a doctoral degree (MD, PhD, DO, DDS, or equivalent) "
            "and have completed all research training but be in the early years of "
            "their first professional appointment at a US institution. Citizenship "
            "requirements apply; see the full programme guidelines. The award "
            "provides salary and research support for up to five years. Dedicated "
            "collaboration funding is also available through the California Walnut "
            "Commission and the VIVA Foundation Physician Research Award. "
            "Applications are submitted through ProposalCentral. The annual proposal "
            "deadline is 1 December."
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
    parser = argparse.ArgumentParser(description="American Heart Association connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  American Heart Association — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  AHA: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
