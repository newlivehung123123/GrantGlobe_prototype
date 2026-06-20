#!/usr/bin/env python3
"""
Schmidt Sciences connector.

Schmidt Sciences (founded 2024 by Eric and Wendy Schmidt) is a science
philanthropy organisation operating five research centres — AI & Advanced
Computing, Astrophysics & Space, Biosciences, Climate, and Science Systems.
It funds ambitious research through internally-developed programmes and does
not generally accept unsolicited proposals.

Current open call covered here:

1. Scaling AI Safety for a Multi-Agent World
   A joint funding call by Schmidt Sciences, Google DeepMind, ARIA (UK),
   the Cooperative AI Foundation, and Google.org. Supports research into
   the safety and trustworthiness of systems composed of multiple
   interacting AI agents.
   Application deadline: 8 August 2026 (11:59 pm AoE).
   Opens: 11 June 2026.

This connector is designed to be re-run as new calls open; schemes with
past deadlines are silently skipped via _advance_deadline (cycle_years=1).

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/schmidt_sciences.py [--dry-run]
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

FUNDER  = "Schmidt Sciences"
DOMAIN  = "api_schmidt"
BASE    = "https://www.schmidtsciences.org"
OPP     = f"{BASE}/opportunities/"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── Scaling AI Safety for a Multi-Agent World ────────────────────────
        "title":   "Scaling AI Safety for a Multi-Agent World",
        "url":     f"{BASE}/opportunity/scaling-ai-safety-for-a-multi-agent-world/",
        "portal":  "https://schmidtsciences.smapply.io/prog/scaling_ai_safety_for_a_multi_agent_world/",
        "deadline": datetime.date(2026, 8, 8),      # 11:59 pm AoE
        "open_threshold_days": 58,                   # portal opened Jun 11 (58d before)
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher", "Mid-Career Researcher",
                       "Senior Researcher", "Postdoctoral Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Science & Technology", "Artificial Intelligence",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "desc": (
            "Scaling AI Safety for a Multi-Agent World is a joint funding call "
            "by Schmidt Sciences, Google DeepMind, the Advanced Research and "
            "Invention Agency (ARIA), the Cooperative AI Foundation, and "
            "Google.org. The call supports research into the safety and "
            "trustworthiness of systems composed of multiple interacting AI "
            "agents — an increasingly critical area as deployed AI systems "
            "become more complex and interconnected. "
            "The programme funds proposals that rigorously address the unique "
            "challenges posed by multi-agent AI environments, including "
            "co-ordination failures, emergent misalignment, and the difficulty "
            "of specifying and verifying safety properties when agent behaviour "
            "is a product of interaction rather than individual design. "
            "Proposals from researchers at universities and non-profit research "
            "institutions worldwide are welcome. The application portal is "
            "SurveyMonkey Apply (SMApply). The deadline is 8 August 2026 "
            "(11:59 pm Anywhere on Earth). The call opened on 11 June 2026."
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
    parser = argparse.ArgumentParser(description="Schmidt Sciences connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Schmidt Sciences — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Schmidt Sciences: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
