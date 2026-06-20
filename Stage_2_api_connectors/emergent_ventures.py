#!/usr/bin/env python3
"""
Emergent Ventures connector.

Emergent Ventures is a low-overhead fellowship and grant programme at the
Mercatus Center at George Mason University. Founded in 2018 and administered
by economist Tyler Cowen, it supports entrepreneurs and researchers with
highly scalable "zero to one" ideas for meaningfully improving society.

The programme accepts applications on a rolling basis throughout the year
with no fixed submission deadline. Award amounts range from small one-off
grants to multi-year fellowship support, calibrated to the nature and scale
of the project. Dedicated tracks are available for projects focused on
India, Africa and the Caribbean, and Ukraine.

This connector represents Emergent Ventures as a single rolling programme.
The sentinel deadline is set far in the future (2035) so it always shows
as Open, in line with the programme's rolling admissions model.

Source: https://www.mercatus.org/emergent-ventures
Portal: https://mercatus.tfaforms.net/5099527

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/emergent_ventures.py [--dry-run]
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

FUNDER  = "Emergent Ventures (Mercatus Center)"
DOMAIN  = "api_emergent_ventures"
BASE    = "https://www.mercatus.org/emergent-ventures"
PORTAL  = "https://mercatus.tfaforms.net/5099527"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── Emergent Ventures (rolling) ───────────────────────────────────────
        "title":    "Emergent Ventures",
        "url":      BASE,
        "portal":   PORTAL,
        # Rolling programme — set a far-future sentinel date so the record
        # is always "Open". _advance_deadline will advance by cycle_years=5
        # once the sentinel passes, keeping the status perpetually open.
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,      # always Open (rolling)
        "cycle_years": 5,
        "grant_types": ["Research Grant", "Fellowship", "Seed Grant"],
        "individual": [
            "Graduate Student", "Postdoctoral Researcher",
            "Early Career Researcher", "Mid-Career Researcher",
            "Senior Researcher", "Entrepreneur", "Independent Scholar",
        ],
        "org_types":  [],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Artificial Intelligence", "Entrepreneurship",
            "Social Innovation", "Economics", "Policy & Governance",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "Emergent Ventures is a low-overhead fellowship and grant programme at "
            "the Mercatus Center at George Mason University. Founded in 2018 and "
            "administered by Tyler Cowen, it supports entrepreneurs and thinkers with "
            "highly scalable 'zero to one' ideas for meaningfully improving society. "
            "The programme funds a wide range of projects: scientific research, "
            "technological innovation, policy analysis, social ventures, and creative "
            "intellectual work. Award amounts are calibrated to the project and can "
            "range from small one-off grants to multi-year fellowship support. There "
            "is no fixed upper or lower limit. "
            "Applicants must be 13 years of age or older. There are no nationality, "
            "institutional affiliation, or disciplinary restrictions: applications "
            "are welcome from students, researchers, entrepreneurs, and independent "
            "thinkers worldwide. "
            "Dedicated funding tracks are available for applicants whose projects "
            "focus specifically on India, Africa and the Caribbean, or Ukraine; "
            "these can be selected from a drop-down menu on the application form. "
            "Fast Grants, a spin-off programme launched in April 2020 to support "
            "COVID-19 science, raised more than $50 million and awarded 260 grants. "
            "Applications are accepted on a rolling basis throughout the year via "
            "the online form at https://mercatus.tfaforms.net/5099527. There is no "
            "fixed deadline; decisions are communicated directly by the programme "
            "team. Questions can be directed to emergentventures@mercatus.org."
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
        "application_deadline_raw":  "Rolling (no fixed deadline)",
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
    parser = argparse.ArgumentParser(description="Emergent Ventures connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Emergent Ventures — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Emergent Ventures: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
