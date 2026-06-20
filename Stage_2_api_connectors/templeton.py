#!/usr/bin/env python3
"""
John Templeton Foundation connector.

The John Templeton Foundation (~$154M/year in grants; $4B endowment) funds
interdisciplinary research and public engagement across six areas: Life
Sciences, Mathematical & Physical Sciences, Character Virtue Development,
Individual Freedom & Free Markets, Public Engagement, and Religion Science
& Society. The Foundation also operates a Ventures programme and
periodically runs targeted Funding Competitions on specific topics.

Grant process:
  All applications begin with an Online Funding Inquiry (OFI), a short
  online form describing the proposed project. OFIs are reviewed on a
  rolling basis between early September and mid-October each year.
  Applicants invited to continue submit a Full Proposal (by December,
  by invitation only). Funding decisions are typically notified by July
  of the following year.

Eligibility:
  The Foundation generally funds charitable organisations worldwide.
  Individuals and for-profit companies may only apply by staff invitation
  and are strongly discouraged from submitting an OFI unprompted.

This connector records two grant entries:
  1. The annual OFI cycle (public-facing entry point, deadline July 15
     each year) — the record researchers should actually apply to.
  2. The Full Proposal stage (December 4, by invitation only) — listed
     separately so researchers know the full-proposal deadline if they
     receive an invitation.

Cycle:
  OFI deadlines fall in mid-July each year; Full Proposal deadlines fall
  in early December. _advance_deadline() advances both by one year when
  the current deadline passes.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/templeton.py [--dry-run]
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

FUNDER  = "John Templeton Foundation"
DOMAIN  = "api_templeton"
BASE    = "https://www.templeton.org"
PORTAL  = "https://portal.templeton.org/"
APPLY   = f"{BASE}/grants/apply-for-grant"
CAL     = f"{BASE}/grants/grant-calendar"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. Online Funding Inquiry (public entry point) ──────────────────
        "title":   "John Templeton Foundation Grants — Online Funding Inquiry",
        "url":     APPLY,
        "deadline": datetime.date(2026, 7, 15),    # annual OFI deadline
        "open_threshold_days": 120,                 # portal opens ~4 months before
        "cycle_years": 1,
        "grant_types": ["Research Grant", "Project Grant"],
        "individual": [],                           # orgs only; individuals by invitation
        "org_types":  ["University", "Research Institution",
                       "Non-Profit Organisation", "Think Tank"],
        "sectors": [
            "Life Sciences", "Science & Technology",
            "Philosophy & Religion", "Social Sciences",
            "Education", "Research & Innovation",
        ],
        "desc": (
            "The John Templeton Foundation ($154M annual giving; $4B endowment) "
            "funds research and public engagement projects that pursue 'the big "
            "questions' — the deepest and most puzzling questions facing humankind "
            "— across six areas: Life Sciences; Mathematical & Physical Sciences; "
            "Character Virtue Development; Individual Freedom & Free Markets; "
            "Public Engagement; and Religion, Science, and Society. The Foundation "
            "also operates a Ventures programme focused on fostering exceptional "
            "cognitive talent and genetics. "
            "All applications begin with an Online Funding Inquiry (OFI), a brief "
            "form requesting a project title, requested amount, key dates, and a "
            "short description of activities, methods, and personnel. OFIs are "
            "reviewed on a rolling basis between early September and mid-October; "
            "applicants whose OFIs are selected receive invitations to submit a "
            "Full Proposal in December, with funding decisions notified by the "
            "following July. "
            "The Foundation generally funds charitable organisations operating "
            "inside and outside the United States. On rare occasions, and by staff "
            "invitation only, it may fund individuals or for-profit companies. "
            "Unsolicited OFIs from individuals or for-profit organisations are "
            "discouraged. The annual OFI deadline is 15 July 2026 (11:59 PM EDT); "
            "due to an expected high volume of requests in 2026, early submission "
            "is strongly recommended."
        ),
    },
    {
        # ── 2. Full Proposal (invitation only, listed for visibility) ────────
        "title":   "John Templeton Foundation — Full Proposal (Invitation Only)",
        "url":     CAL,
        "deadline": datetime.date(2026, 12, 4),    # FP deadline
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant", "Project Grant"],
        "individual": [],
        "org_types":  ["University", "Research Institution",
                       "Non-Profit Organisation", "Think Tank"],
        "sectors": [
            "Life Sciences", "Science & Technology",
            "Philosophy & Religion", "Social Sciences",
            "Education", "Research & Innovation",
        ],
        "desc": (
            "The John Templeton Foundation Full Proposal stage is open only to "
            "applicants invited following review of their Online Funding Inquiry "
            "(OFI). Invitations are sent by early October each year. The Full "
            "Proposal webform (available in the Templeton Portal on the day of "
            "invitation) requires a detailed project narrative, budget, timeline, "
            "and supplemental documents, and allows designation of external "
            "reviewers. Full Proposals submitted by 4 December 2026 are reviewed "
            "by the Foundation's Board of Trustees and President, with funding "
            "decisions notified by July 2027. Applicants should first submit an "
            "OFI (deadline 15 July 2026) before expecting an invitation. The "
            "Foundation funds charitable organisations worldwide across its six "
            "funding areas: Life Sciences; Mathematical & Physical Sciences; "
            "Character Virtue Development; Individual Freedom & Free Markets; "
            "Public Engagement; and Religion, Science, and Society."
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
        "funding_amount_min":        None,
        "funding_amount_max":        None,
        "currency":                  "USD",
        "thematic_sectors":          scheme["sectors"],
        "grant_types":               scheme["grant_types"],
        "applicant_base_regions":    ["Global"],
        "geographic_focus_regions":  ["Global"],
        "applicant_base_countries":  [],
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
    parser = argparse.ArgumentParser(description="John Templeton Foundation connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Templeton — {len(records)} schemes  (today: {today})")
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
    print(f"\n  Templeton: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
