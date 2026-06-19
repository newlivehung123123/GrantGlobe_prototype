#!/usr/bin/env python3
"""
Weatherhead Center for International Affairs (Harvard University) —
Weatherhead Scholars Program connector.

The Weatherhead Scholars Program offers visiting scholars, postdoctoral
researchers, and experienced practitioners up to one academic year in
residence at Harvard. Critically, the Practitioner Fellow track is
explicitly open to non-academics — diplomats, journalists, private-sector
leaders, military officers, elected officials, and civil-society
professionals — alongside the academic Visiting Scholar and Postdoctoral
Fellow tracks.

The source page states two distinct, exact deadlines for the 2026-2027
cycle: "Postdoctoral Fellows and Visiting Scholars: October 15, 2025" and
"Practitioner Fellows: March 5, 2026." Both dates have already passed as
of this connector's construction, so each is advanced by one annual cycle
(cycle_years=1) under this pipeline's standard convention to project the
next cycle's deadline.

Source: https://www.wcfia.harvard.edu/funding/weatherhead-scholars-program

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/weatherhead_center.py [--dry-run]
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

FUNDER = "Weatherhead Center for International Affairs (Harvard University)"
DOMAIN = "api_weatherhead_center"
SOURCE_URL = "https://www.wcfia.harvard.edu/funding/weatherhead-scholars-program"
PORTAL_URL = "https://scholarsprogram.wcfia.harvard.edu/weatherhead-scholars-program"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title": "Weatherhead Scholars Program — Postdoctoral Fellows & Visiting Scholars",
        # Sourced exactly: "October 15, 2025".
        "deadline": datetime.date(2025, 10, 15),
        "individual": ["Researcher", "Post-doctoral Scholar", "Faculty"],
        "desc": (
            "Up to one academic year at Harvard for tenured/tenure-track "
            "faculty (Visiting Scholars) and recent PhD recipients "
            "(Postdoctoral Fellows in International Affairs) working on "
            "international, comparative, transnational, or global "
            "issues in the social sciences. Visiting Scholars are "
            "generally expected to secure their own funding through "
            "sabbatical salary or external grants; Postdoctoral Fellows "
            "must have earned their PhD within the past three years or "
            "be scheduled to defend by the start of the appointment."
        ),
    },
    {
        "title": "Weatherhead Scholars Program — Practitioner Fellows",
        # Sourced exactly: "March 5, 2026".
        "deadline": datetime.date(2026, 3, 5),
        "individual": ["Practitioner", "Journalist", "Diplomat", "Civil Society Professional"],
        "desc": (
            "Up to one academic year at Harvard for experienced "
            "practitioners from diplomacy, journalism, private-sector "
            "leadership, the military, elected office, public service, "
            "and civil society. Open to applicants from the United "
            "States and around the world who hold at least a bachelor's "
            "degree and have a track record of professional impact; "
            "candidates may apply individually or be nominated by a "
            "sponsoring institution. Not restricted to academics."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("url", SOURCE_URL)
    _s.setdefault("portal", PORTAL_URL)
    _s.setdefault("cycle_years", 1)
    _s.setdefault("open_threshold_days", 90)
    _s.setdefault("amount_min", None)
    _s.setdefault("amount_max", None)
    _s.setdefault("sectors", ["International Affairs", "Political Science"])
    _s.setdefault("grant_types", ["Fellowship"])
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
    parser = argparse.ArgumentParser(description="Weatherhead Center connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Weatherhead Center — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Weatherhead Center: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
