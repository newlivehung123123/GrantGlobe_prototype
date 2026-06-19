#!/usr/bin/env python3
"""
Simons Foundation connector.

The Simons Foundation (~$200M/year in grants) funds basic research in
mathematics, theoretical physics, life sciences, and autism neuroscience
(via SFARI). Programs span individual fellowships, team collaborations,
and targeted research grants.

Divisions:
  - Mathematics & Physical Sciences (MPS)
  - Life Sciences
  - Autism & Neuroscience (SFARI)

Annual patterns:
  - Simons Fellows (Math & Physics): deadline ~October each year
  - Simons Collaborations in MPS: LOI ~October, Full Proposal ~February
  - Collaboration Grants for Mathematicians: ~February each year
  - Simons Investigators: ~February each year (institutional nomination required)
  - Life Sciences programs: various deadlines
  - SFARI: multiple rolling and annual programs

Because simonsfoundation.org may not be directly crawlable from the server,
this connector uses a curated static list of programs updated from
public sources. Deadlines for "Open" programs are confirmed; "Forthcoming"
dates are pattern-based estimates — verify at simonsfoundation.org.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/simons_foundation.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FUNDER  = "Simons Foundation"
DOMAIN  = "api_simons"
SF_BASE = "https://www.simonsfoundation.org"
SFARI   = "https://www.sfari.org"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Program definitions
# (deadline, status, title, url, description, grant_types, individual_eligibility, sectors)
# ---------------------------------------------------------------------------

PROGRAMS: list[dict] = [
    # ── Life Sciences ─────────────────────────────────────────────────────────
    {
        "title":      "Simons Foundation: Synthetic Plant Biology",
        "url":        f"{SF_BASE}/grant/synthetic-plant-biology/",
        "deadline":   datetime.date(2026, 7, 1),
        "status":     "Open",
        "grant_types": ["Research Grant"],
        "individual": [],
        "org_types":  ["University", "Research Institution"],
        "sectors":    ["Agriculture & Food", "Research & Innovation", "Health Sciences"],
        "desc": (
            "The Simons Foundation Synthetic Plant Biology program supports research that "
            "applies engineering principles to advance our understanding of how plants function. "
            "Awards support basic research into the molecular and genetic mechanisms of plant "
            "biology, with an emphasis on quantitative and systems-level approaches. "
            "Applications submitted via the Simons Award Manager (SAM)."
        ),
    },

    # ── Mathematics & Physical Sciences ──────────────────────────────────────
    {
        "title":      "Simons Fellows in Mathematics",
        "url":        f"{SF_BASE}/grant/simons-fellows-in-mathematics/",
        "deadline":   datetime.date(2026, 10, 1),
        "status":     "Open",
        "grant_types": ["Fellowship"],
        "individual": ["Faculty Researcher"],
        "org_types":  ["University"],
        "sectors":    ["Research & Innovation", "Science & Technology"],
        "desc": (
            "Simons Fellows in Mathematics extend sabbatical research leaves from a single "
            "term to a full academic year. Fellows receive up to 50% salary replacement "
            "(maximum USD 125,000) plus up to USD 10,000 in leave-related expenses. "
            "Eligibility: faculty in mathematics departments with an active research program. "
            "Applications via the Simons Award Manager (SAM). Applications from researchers "
            "from underrepresented groups are especially encouraged."
        ),
    },
    {
        "title":      "Simons Fellows in Theoretical Physics",
        "url":        f"{SF_BASE}/grant/simons-fellows-in-theoretical-physics/",
        "deadline":   datetime.date(2026, 10, 1),   # pattern: same cycle as Math Fellows
        "status":     "Forthcoming",
        "grant_types": ["Fellowship"],
        "individual": ["Faculty Researcher"],
        "org_types":  ["University"],
        "sectors":    ["Research & Innovation", "Science & Technology"],
        "desc": (
            "Simons Fellows in Theoretical Physics extend sabbatical research leaves to a full "
            "academic year for faculty working in theoretical physics and related areas. "
            "Covers salary replacement (up to 50%, maximum USD 125,000) and expenses. "
            "Typical deadline is early October; verify at simonsfoundation.org. "
            "Applications via the Simons Award Manager (SAM)."
        ),
    },
    {
        "title":      "Simons Collaborations in Mathematics and the Physical Sciences (LOI)",
        "url":        f"{SF_BASE}/grant/simons-collaborations-in-mathematics-and-the-physical-sciences/",
        "deadline":   datetime.date(2026, 10, 29),  # pattern: late October LOI each year
        "status":     "Forthcoming",
        "grant_types": ["Research Grant"],
        "individual": [],
        "org_types":  ["University", "Research Institution"],
        "sectors":    ["Research & Innovation", "Science & Technology"],
        "desc": (
            "Simons Collaborations in Mathematics and the Physical Sciences fund large-scale, "
            "multi-year collaborative efforts on fundamental problems in mathematics, "
            "theoretical physics, or theoretical computer science. Awards are typically "
            "USD 2–8 million over 4 years. Two-step process: Letter of Intent (LOI) "
            "~October, then Full Proposal ~February. Up to 3 new collaborations awarded "
            "per cycle. Applications via the Simons Award Manager (SAM); collaboration "
            "directors must be at eligible US or international institutions."
        ),
    },
    {
        "title":      "Simons Collaboration Grants for Mathematicians",
        "url":        f"{SF_BASE}/grant/collaboration-grants-for-mathematicians/",
        "deadline":   datetime.date(2027, 2, 1),    # pattern: early February each year
        "status":     "Forthcoming",
        "grant_types": ["Research Grant"],
        "individual": ["Faculty Researcher"],
        "org_types":  ["University"],
        "sectors":    ["Research & Innovation", "Science & Technology"],
        "desc": (
            "Simons Collaboration Grants for Mathematicians provide USD 10,000 per year "
            "for 5 years to support active collaborative research in mathematics. "
            "Intended for faculty not yet at the level of Simons Investigators, enabling "
            "them to initiate new collaborations, support postdoctoral researchers, and "
            "attend conferences. Applicants must hold a tenured or tenure-track position at "
            "a US academic institution. Deadline typically in early February each year."
        ),
    },
    {
        "title":      "Simons Investigators",
        "url":        f"{SF_BASE}/grant/simons-investigators/",
        "deadline":   datetime.date(2027, 2, 1),    # pattern: February institutional nomination
        "status":     "Forthcoming",
        "grant_types": ["Research Grant", "Fellowship"],
        "individual": ["Faculty Researcher"],
        "org_types":  ["University"],
        "sectors":    ["Research & Innovation", "Science & Technology"],
        "desc": (
            "Simons Investigators are outstanding theoretical scientists who receive long-term "
            "research support (USD 100,000 per year for 5 years, renewable). Programs cover "
            "Mathematics, Physics, Astrophysics, Computational & Evolutionary Molecular Biology, "
            "and Mathematical Modeling of Living Systems. Nominations are made by the head of "
            "mathematics or physics department — individuals cannot apply directly. "
            "Nomination deadline is typically in February."
        ),
    },

    # ── SFARI (Autism & Neuroscience) ─────────────────────────────────────────
    {
        "title":      "SFARI Fellows-to-Faculty Award",
        "url":        f"{SF_BASE}/grant/fellows-to-faculty-award/",
        "deadline":   datetime.date(2026, 10, 15),  # expected launch October 2026
        "status":     "Forthcoming",
        "grant_types": ["Fellowship", "Research Grant"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  ["University", "Research Institution"],
        "sectors":    ["Health Sciences", "Research & Innovation"],
        "desc": (
            "SFARI Fellows-to-Faculty Awards support senior postdoctoral researchers "
            "transitioning to independent faculty positions in autism research. Recipients "
            "receive funding to bridge their postdoctoral training with an independent "
            "career, including protected research time and resources. Applications open "
            "approximately October each year via the SFARI Award Manager. Investigators "
            "who have not previously been funded by SFARI are especially encouraged."
        ),
    },
    {
        "title":      "SFARI New Ideas Award",
        "url":        f"{SFARI}/grant/new-ideas-request-for-applications/",
        "deadline":   datetime.date(2026, 11, 1),   # rolling/annual; estimated next cycle
        "status":     "Forthcoming",
        "grant_types": ["Research Grant"],
        "individual": [],
        "org_types":  ["University", "Research Institution"],
        "sectors":    ["Health Sciences", "Research & Innovation"],
        "desc": (
            "SFARI New Ideas Awards fund exploratory, novel research projects related to "
            "autism and associated neurodevelopmental conditions. Awards of USD 50,000–100,000 "
            "support early-stage studies that could not yet obtain funding through "
            "conventional mechanisms. Applicants do not need prior experience in autism "
            "research. Applications submitted via the SFARI Award Manager; investigators "
            "not previously funded by SFARI are especially encouraged to apply."
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


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _build_record(prog: dict) -> dict:
    today = datetime.date.today()
    deadline = prog["deadline"]

    # If estimated date has already passed, advance by one year
    if deadline < today:
        try:
            deadline = deadline.replace(year=deadline.year + 1)
        except ValueError:
            deadline = datetime.date(deadline.year + 1, deadline.month, 28)

    deadline_iso = deadline.isoformat()
    deadline_raw = str(deadline.day) + " " + deadline.strftime("%B %Y")

    return {
        "grant_title":              prog["title"],
        "funder_name":              FUNDER,
        "source_url":               prog["url"],
        "application_portal_url":   "https://sam.simonsfoundation.org/",
        "description":              prog["desc"],
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       None,
        "current_status":           prog["status"],
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         prog["sectors"],
        "grant_types":              prog["grant_types"],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["Global"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       prog["org_types"],
        "individual_eligibility":   prog["individual"],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(prog["url"], prog["title"], deadline_iso),
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM grants WHERE source_url = %s",
        (record["source_url"],)
    )
    existing = cur.fetchone()
    if existing:
        cur.execute(
            """UPDATE grants SET
                grant_title = %s, description = %s,
                application_deadline = %s, application_deadline_raw = %s,
                current_status = %s, crawl_date = %s, content_hash = %s
               WHERE id = %s""",
            (
                record["grant_title"], record["description"],
                record["application_deadline"], record["application_deadline_raw"],
                record["current_status"], record["crawl_date"], record["content_hash"],
                existing[0],
            ),
        )
        return "updated"
    cols = list(record.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        [record[c] for c in cols],
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="Simons Foundation connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(p) for p in PROGRAMS]

    print(f"  Total: {len(records)} records")
    for r in records:
        print(f"  [{r['current_status']:12s}] {r['grant_title'][:65]}  → {r['application_deadline']}")

    if args.dry_run:
        print("\n[DRY RUN] Full records:")
        for r in records:
            print(json.dumps(r, indent=2, default=str))
        return

    conn = _connect()
    inserted = updated = err = 0
    for record in records:
        try:
            result = _upsert(conn, record)
            conn.commit()
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            conn.rollback()
            print(f"  DB error [{record['grant_title'][:50]}]: {e}")
            err += 1
    conn.close()
    print(f"\nDone: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
