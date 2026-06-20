#!/usr/bin/env python3
"""
CLR Fund (Center on Long-Term Risk) connector.

The CLR Fund, managed by the Center on Long-Term Risk, supports research and
career-development work relevant to reducing risks of astronomical suffering
(s-risks), including work on multi-agent AI safety, cooperative AI, and
bargaining/conflict scenarios involving advanced AI systems. Grant decisions
are made by a panel of fund managers. Recipients may be charitable
organisations, academic institutions, or individuals — the fund's own
grantmaking-process page explicitly lists individuals as an eligible
recipient category alongside institutions, and historical payouts include
independent researchers, tuition/stipend support, and PhD students without
requiring institutional affiliation as a precondition of funding.

Deadline pattern — rolling, no fixed deadline (same sentinel-date convention
as LTFF/EAIF elsewhere in this codebase).

Source: https://longtermrisk.org/grantmaking/
Portal: https://docs.google.com/forms/d/e/1FAIpQLScFI4LTTVi5XBphdoMrVI1kAAE7Dei0FLebxDq7dx52r7XgKg/viewform?usp=sf_link

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/clr_fund.py [--dry-run]
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

FUNDER = "CLR Fund (Center on Long-Term Risk)"
DOMAIN = "api_clr_fund"
BASE   = "https://longtermrisk.org/grantmaking/"
PORTAL = (
    "https://docs.google.com/forms/d/e/"
    "1FAIpQLScFI4LTTVi5XBphdoMrVI1kAAE7Dei0FLebxDq7dx52r7XgKg/"
    "viewform?usp=sf_link"
)

DESC = (
    "The CLR Fund, managed by the Center on Long-Term Risk, supports "
    "research and career-development work relevant to reducing risks of "
    "astronomical suffering (s-risks), with a strong focus on multi-agent "
    "AI safety, cooperative AI, and bargaining or conflict scenarios "
    "involving advanced AI systems. The fund's grantmaking-process page "
    "explicitly states that recipients 'may be charitable organizations, "
    "academic institutions, or individuals' and that grant decisions are "
    "made by a simple majority of fund managers on a rolling basis. "
    "Historical payouts have funded independent researchers, tuition and "
    "stipend support, and PhD students, without requiring institutional "
    "affiliation as a precondition of funding; the fund states it is "
    "interested in supporting anyone who 'can somehow do high-quality work "
    "relevant to s-risks,' regardless of background. Applications are "
    "accepted on a rolling basis with no fixed deadline. Apply via the "
    "online form linked from the programme page."
)

SCHEMES: list[dict] = [
    {
        "title":   "CLR Fund",
        "url":     BASE,
        "portal":  PORTAL,
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": ["Research Grant", "Project Grant", "Stipend"],
        "individual": [
            "Independent Researcher", "Independent Scholar",
            "PhD Student", "Early Career Researcher", "Mid-Career Researcher",
        ],
        "org_types": ["Non-Profit Organisation", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Artificial Intelligence", "AI Safety",
            "Existential Risk Reduction", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Global"],
        "focus_countries": [],
        "desc": DESC,
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
    parser = argparse.ArgumentParser(description="CLR Fund connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  CLR Fund — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  CLR Fund: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
