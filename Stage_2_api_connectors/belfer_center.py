#!/usr/bin/env python3
"""
Belfer Center for Science and International Affairs (Harvard Kennedy
School) — Fellowships connector.

The Belfer Center runs roughly a dozen named fellowship programs for the
2027-2028 academic year, all sharing a single, page-level application
window stated directly on the fellowships page: "The application period
for the 2026-2027 academic year has closed. Applications for the
2027-2028 academic year will open on October 1, 2026 and close on
December 1, 2026. Recommendation letters will be due December 15, 2026."

This connector covers the four named fellowships most directly relevant
to AI, emerging technology, and international-security policy: the
Technology and Geopolitics Fellowship (hosted by the Program on Emerging
Technology, Scientific Advancement, and Global Policy), the Nova
Fellowship (for senior practitioners in AI, biotechnology, quantum
computing, space, and other emerging-technology domains), the
International Security Program Fellowship, and the Managing the Atom
(nuclear policy) Fellowship. Several further, more regionally/topically
specific fellowships exist on the same page (Ernest May, Emirates
Leadership Initiative, Kuwait Program, Belfer Young Leaders, Geopolitics
of Energy, Arctic Initiative, Recanati-Kaplan Foundation Fellowship for
intelligence officers, Energy/Climate/Technology Policy) but are excluded
here as outside this pipeline's AI/tech-and-security-policy focus.

Source: https://www.belfercenter.org/fellowships

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/belfer_center.py [--dry-run]
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

FUNDER = "Belfer Center for Science and International Affairs (Harvard Kennedy School)"
DOMAIN = "api_belfer_center"
PORTAL_GENERAL = "https://www.belfercenter.org/fellowships"
ORG_NONE: list[str] = []

# Application period opens October 1, 2026 and closes December 1, 2026
# (recommendation letters due December 15, 2026) — directly sourced from
# the fellowships page itself, so the opening date is exact, not estimated.
DEADLINE = datetime.date(2026, 12, 1)
OPEN_DATE = datetime.date(2026, 10, 1)
OPEN_THRESHOLD_DAYS = (DEADLINE - OPEN_DATE).days  # exact, sourced window

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title": "Belfer Center Technology and Geopolitics Fellowship",
        "desc": (
            "Hosted by the Program on Emerging Technology, Scientific "
            "Advancement, and Global Policy (ETSAGP), this fellowship is "
            "for current doctoral students in the dissertation-writing "
            "stage and recent recipients of a PhD or equivalent degree, "
            "researching the intersection of technology and geopolitics."
        ),
    },
    {
        "title": "Belfer Center Nova Fellowship",
        "desc": (
            "The Nova Fellowship invites applications from outstanding "
            "senior practitioners in fields such as AI, biotechnology, "
            "quantum computing, space, and other emerging-technology "
            "domains, with preference given to private-sector innovators, "
            "founders, and researchers."
        ),
    },
    {
        "title": "Belfer Center International Security Program Fellowship",
        "desc": (
            "A fellowship within the Belfer Center's International "
            "Security Program, supporting research on international "
            "security, defense policy, and related strategic-studies "
            "topics."
        ),
    },
    {
        "title": "Belfer Center Managing the Atom Fellowship",
        "desc": (
            "A fellowship within the Belfer Center's Managing the Atom "
            "project, supporting research on nuclear weapons policy, "
            "nuclear energy, and nonproliferation."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("url", PORTAL_GENERAL)
    _s.setdefault("portal", PORTAL_GENERAL)
    _s.setdefault("deadline", DEADLINE)
    _s.setdefault("cycle_years", 1)
    _s.setdefault("open_threshold_days", OPEN_THRESHOLD_DAYS)
    _s.setdefault("amount_min", None)
    _s.setdefault("amount_max", None)
    _s.setdefault("sectors", ["Emerging Technology", "International Security"])
    _s.setdefault("individual", ["Researcher", "PhD Candidate", "Senior Practitioner"])
    _s.setdefault("grant_types", ["Fellowship"])
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])
    _s.setdefault("focus_countries", ['US'])


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
        "applicant_base_regions":    ["Global"],
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
    parser = argparse.ArgumentParser(description="Belfer Center fellowships connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Belfer Center — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Belfer Center: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
