#!/usr/bin/env python3
"""
Long-Term Future Fund (LTFF) connector.

The Long-Term Future Fund is one of the EA Funds (administered by the
Effective Ventures Foundation) dedicated to improving the long-term outlook
for humanity, with a strong focus on reducing risks from advanced AI. It
funds independent researchers, organisations, and individuals working on
AI alignment and safety, biosecurity, and other catastrophic and existential
risk reduction projects.

The fund accepts applications on a rolling basis throughout the year with
no fixed submission deadline. Grant decisions are made periodically by a
panel of fund managers as applications accumulate.

This connector represents LTFF as a single rolling programme. The sentinel
deadline is set far in the future (2035) so it always shows as Open, in
line with the programme's rolling admissions model — the same pattern used
for Emergent Ventures.

Source: https://funds.effectivealtruism.org/funds/far-future
Portal: https://av20jp3z.paperform.co/?fund=Long-Term%20Future%20Fund

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/ltff.py [--dry-run]
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

FUNDER  = "Long-Term Future Fund (EA Funds)"
DOMAIN  = "api_ltff"
BASE    = "https://funds.effectivealtruism.org/funds/far-future"
PORTAL  = "https://av20jp3z.paperform.co/?fund=Long-Term%20Future%20Fund"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── Long-Term Future Fund (rolling) ──────────────────────────────────
        "title":    "Long-Term Future Fund",
        "url":      BASE,
        "portal":   PORTAL,
        # Rolling programme — set a far-future sentinel date so the record
        # is always "Open". _advance_deadline will advance by cycle_years=5
        # once the sentinel passes, keeping the status perpetually open.
        "deadline": datetime.date(2035, 12, 31),
        "open_threshold_days": 3500,      # always Open (rolling)
        "cycle_years": 5,
        "grant_types": ["Research Grant", "Project Grant"],
        "individual": [
            "Graduate Student", "Postdoctoral Researcher",
            "Early Career Researcher", "Mid-Career Researcher",
            "Senior Researcher", "Independent Scholar",
        ],
        "org_types":  ["Non-Profit Organisation", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Artificial Intelligence", "Science & Technology",
            "Research & Innovation", "Biosecurity",
            "Existential Risk Reduction", "Policy & Governance",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The Long-Term Future Fund (LTFF) is one of the EA Funds, managed "
            "by Effective Ventures Foundation, dedicated to improving the "
            "long-term outlook for humanity. The fund's primary focus is "
            "reducing risks from advanced artificial intelligence: it supports "
            "research and projects on AI alignment, AI safety, AI governance, "
            "and related existential-risk topics, alongside work on "
            "biosecurity and other catastrophic risk reduction. "
            "The fund supports a wide range of project types, including "
            "independent research, organisational operating costs, academic "
            "research, and skill-building activities such as PhDs, retraining, "
            "or upskilling for a relevant career. Past grantees have included "
            "individual researchers, early-stage organisations, and "
            "established non-profits. "
            "Applications are accepted on a rolling basis throughout the year "
            "via an online form; there is no fixed deadline. Grant decisions "
            "are made periodically by a panel of fund managers as applications "
            "accumulate, with most applicants hearing back within 1-2 months. "
            "A public database of past grant payouts and a description of the "
            "fund's grantmaking approach are available on the fund's page. "
            "Apply via the online form at "
            "https://av20jp3z.paperform.co/?fund=Long-Term%20Future%20Fund."
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
    parser = argparse.ArgumentParser(description="LTFF connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Long-Term Future Fund — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  LTFF: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
