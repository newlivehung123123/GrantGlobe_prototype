#!/usr/bin/env python3
"""
Centre for the Governance of AI (GovAI) connector.

GovAI is a UK/US-based AI-governance research nonprofit (a US 501(c)(3),
with a UK subsidiary, GovAI UK, registered as a company limited by
guarantee). Its `/opportunities` page lists currently-open, dated
fellowship and program opportunities; this connector covers the four such
opportunities found there as of this scouting pass. (The page also lists
staff job openings — Director of Operations, People Operations roles — which
are excluded here as out of scope for a grant-discovery pipeline, not
fellowships/grants.)

Three prior attempts to locate this content at other URL slugs
(/get-involved, /fellowships, /summer-fellowship) all returned blank,
client-rendered shells; the correct, fully server-rendered URL was
eventually found via web search rather than guessed.

Source: https://www.governance.ai/opportunities

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/govai.py [--dry-run]
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

FUNDER = "Centre for the Governance of AI (GovAI)"
DOMAIN = "api_govai"
PORTAL_GENERAL = "https://www.governance.ai/opportunities"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title": "GovAI DC Winter Fellowship 2027",
        # Deadline: Sunday, July 12, 2026 at 11:59PM ET.
        "deadline":   datetime.date(2026, 7, 12),
        "open_threshold_days": 60,
        "focus_countries": ["US"],  # CHAR(2)[] column — ISO-2 code, not full name
        "desc": (
            "A three-month, bipartisan fellowship designed to accelerate "
            "or launch impactful careers in American AI governance and "
            "policy. Winter Fellows join GovAI in Washington, DC, from "
            "January 18 to April 9, 2027, working on research or applied "
            "policy projects relevant to AI governance."
        ),
    },
    {
        "title": "GovAI UK Winter Fellowship 2027 — Research Track",
        # Deadline: 23:59 BST Sunday 12 July 2026.
        "deadline":   datetime.date(2026, 7, 12),
        "open_threshold_days": 60,
        "focus_countries": ["GB"],  # CHAR(2)[] column — ISO-2 code, not full name
        "desc": (
            "Winter Fellows on the Research Track join GovAI in London "
            "from 18 January to 9 April 2027 and conduct a research "
            "project of their own choosing relevant to AI governance and "
            "policy."
        ),
    },
    {
        "title": "GovAI UK Winter Fellowship 2027 — Applied Track",
        # Deadline: 23:59 BST Sunday 12 July 2026.
        "deadline":   datetime.date(2026, 7, 12),
        "open_threshold_days": 60,
        "focus_countries": ["GB"],  # CHAR(2)[] column — ISO-2 code, not full name
        "desc": (
            "Winter Fellows on the Applied Track join GovAI in London "
            "from 18 January to 9 April 2027, working on non-research "
            "projects pitched by GovAI or partner organisations (in "
            "Summer 2026, partners included the UK's AI Security "
            "Institute, the Centre for Long-Term Resilience, Far.AI, and "
            "the Oxford Martin School AI Governance Initiative)."
        ),
    },
    {
        "title": "GovAI U.S. AI Policy Program",
        # Deadline: Sunday, July 5, 2026 at 11:59PM ET.
        "deadline":   datetime.date(2026, 7, 5),
        "open_threshold_days": 60,
        "focus_countries": ["US"],  # CHAR(2)[] column — ISO-2 code, not full name
        "desc": (
            "A bipartisan, part-time, 12-week program designed to "
            "accelerate or launch careers in US AI policy, open to US "
            "policy professionals across government and think tanks. "
            "Runs from early September to early December 2026 at roughly "
            "5 hours per week, offered free of charge."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("url", PORTAL_GENERAL)
    _s.setdefault("portal", PORTAL_GENERAL)
    _s.setdefault("cycle_years", 1)
    _s.setdefault("amount_min", None)
    _s.setdefault("amount_max", None)
    _s.setdefault("sectors", ["AI Governance", "AI Policy"])
    _s.setdefault("individual", ["Researcher", "Policy Professional", "Early-Career Professional"])
    _s.setdefault("grant_types", ["Fellowship"])
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])


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
    parser = argparse.ArgumentParser(description="GovAI connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  GovAI — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  GovAI: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
