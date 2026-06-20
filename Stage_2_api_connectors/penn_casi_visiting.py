#!/usr/bin/env python3
"""
CASI Visiting Scholars/Fellows Program (Center for the Advanced Study of
India, University of Pennsylvania) connector.

CASI's Visiting Scholars/Fellows Program brings individuals "with
different areas of expertise from academia, the bureaucracy and civil
services, NGOs, and civil society (such as media)" to Penn for residencies
of one to three months. The official Eligibility Guidelines section states
plainly: "Applicants for our academic or researcher track must hold a
PhD. Applicants for our policymaker/civil society/media track must have a
minimum of 5 years' experience and preferably a masters in their chosen
field" — i.e. alongside the standard PhD-holding academic/researcher
track, there is a parallel, explicitly named track for policymakers,
civil-servants, NGO staff, and media/civil-society professionals that
carries no PhD or university-affiliation requirement whatsoever; only
five years of relevant professional experience (a master's degree is
"preferred," not required).

This mirrors the eligibility profile of other dual-track practitioner/
academic fellowships already in this pipeline (e.g. UCL Liberating the
Collections, AFSEE at LSE), with the distinguishing feature that CASI's
own published guidelines explicitly carve out a named "policymaker/civil
society/media" track as a parallel, equally valid path to the academic
track.

The Fellowship provides furnished accommodation near campus, roundtrip
economy international airfare to Philadelphia, a monthly living stipend,
and a modest research fund; no specific dollar figures are publicly
disclosed for the stipend or research fund. Fellows participate in CASI
events, engage in their own research projects, present in the CASI
seminar series, and contribute a short article to India in Transition,
CASI's biweekly publication.

The official application page confirms: "Applications for the 2025-2026
Academic Year (beginning September 2025 through May 2026) are accepted
through January 2, 2025, at 11:59 PM EST" — this date has already passed
as of this connector's construction, and a parallel web search confirms
the program has since opened applications for the 2026-27 Academic Year
on the same annual cycle. The program recurs annually on this same
autumn-application/January-deadline pattern, so the deadline is advanced
by one annual cycle (cycle_years=1) under this pipeline's standard
convention.

Source: https://casi.sas.upenn.edu/visiting-scholar-fellow-in-residence

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/penn_casi_visiting.py [--dry-run]
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

FUNDER = "CASI Visiting Scholars/Fellows Program (Center for the Advanced Study of India, University of Pennsylvania)"
DOMAIN = "api_penn_casi_visiting"
SOURCE_URL = "https://casi.sas.upenn.edu/visiting-scholar-fellow-in-residence"
PORTAL_URL = SOURCE_URL
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "CASI Visiting Scholar/Fellow In-Residence — Policymaker/Civil Society/Media Track",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "Applications for the 2025-2026 Academic Year ... are
        # accepted through January 2, 2025, at 11:59 PM EST." Already
        # passed at construction; program confirmed to recur annually
        # (2026-27 cycle subsequently opened on the same pattern).
        "deadline":   datetime.date(2025, 1, 2),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["South Asian Studies", "Public Policy", "Area Studies", "Journalism"],
        "individual": ["Policymaker", "Practitioner", "Civil Servant", "Journalist"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": ["South Asia"],
        "focus_countries": ["IN"],  # CHAR(2)[] column — ISO-2 code, not full name
        "desc": (
            "A one-to-three-month residency at the Center for the "
            "Advanced Study of India (CASI), School of Arts & Sciences, "
            "University of Pennsylvania, bringing individuals 'with "
            "different areas of expertise from academia, the bureaucracy "
            "and civil services, NGOs, and civil society (such as "
            "media)' to engage in scholarly research on contemporary "
            "India, present in the CASI seminar series, and contribute a "
            "short article to India in Transition, CASI's biweekly "
            "publication. The official Eligibility Guidelines state: "
            "'Applicants for our academic or researcher track must hold "
            "a PhD. Applicants for our policymaker/civil society/media "
            "track must have a minimum of 5 years' experience and "
            "preferably a masters in their chosen field' — the "
            "policymaker/civil-society/media track carries no PhD or "
            "university-affiliation requirement; a master's degree is "
            "preferred but not required. The Fellowship provides "
            "furnished accommodation near campus, roundtrip economy "
            "international airfare to Philadelphia, a monthly living "
            "stipend, and a modest research fund (no specific dollar "
            "figures publicly disclosed). The program 'strongly "
            "encourages applications from women, minorities, and "
            "under-represented communities.'"
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])
    _s.setdefault("focus_countries", [])


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
# DB upsert (composite key: source_url + grant_title)
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
    parser = argparse.ArgumentParser(description="Penn CASI Visiting Scholars/Fellows connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Penn CASI Visiting Scholars/Fellows Program — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Penn CASI Visiting Scholars/Fellows Program: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
