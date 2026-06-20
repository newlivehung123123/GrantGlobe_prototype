#!/usr/bin/env python3
"""
Centre for Research in the Arts, Social Sciences and Humanities (CRASSH,
University of Cambridge) — Visiting Fellowships connector.

CRASSH Visiting Fellowships are open to any PhD-holding scholar from
outside the University of Cambridge working broadly within the arts,
humanities, or social sciences (interdisciplinary scholars working on
medicine, engineering, or the natural sciences are also welcome). Visiting
Fellows pursue independent research with no academic supervision, and are
given a desk, IT support, and full library access; the Fellowship is
self-funded (Fellows must have their own funding in place, plus a
University visitor's fee).

The source page's published deadline table states exactly: "1 November
2025 | Fellowships to be held between October 2026 and June 2027." That
deadline has already passed as of this connector's construction; the
table's prior-year row ("1 November 2024 -> October 2025-June 2026")
confirms this is a stable annual deadline, so it is advanced by one cycle
(cycle_years=1) under this pipeline's standard convention to project the
next (1 November 2026) round.

Source: https://www.crassh.cam.ac.uk/research/fellowships/visiting-fellowships/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/crassh_cambridge.py [--dry-run]
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

FUNDER = "Centre for Research in the Arts, Social Sciences and Humanities (CRASSH, University of Cambridge)"
DOMAIN = "api_crassh_cambridge"
SOURCE_URL = "https://www.crassh.cam.ac.uk/research/fellowships/visiting-fellowships/"
PORTAL_URL = "https://www.crassh.cam.ac.uk/research/fellowships/visiting-fellowships/"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "CRASSH Visiting Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: "1 November 2025" (for fellowships held between
        # October 2026 and June 2027); advanced one annual cycle per this
        # pipeline's standard convention since that date has passed.
        "deadline":   datetime.date(2025, 11, 1),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Arts", "Humanities", "Social Sciences"],
        "individual": ["Researcher", "Faculty", "Post-doctoral Scholar"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A self-funded Visiting Fellowship at Cambridge's CRASSH "
            "centre, held for one term (2-3 months), two terms (5-6 "
            "months), three terms (9 months), or 11 months. Open to any "
            "PhD-holding scholar from outside the University of "
            "Cambridge working broadly within the arts, humanities, or "
            "social sciences (interdisciplinary work touching medicine, "
            "engineering, or the natural sciences is also welcome). "
            "Fellows pursue independent research without formal academic "
            "supervision and receive a desk, IT support, and full "
            "University library access; they must have their own "
            "funding in place to cover travel, accommodation, and "
            "living expenses, plus a University visitor's fee (£2,400 "
            "per year, £720 per term, or £90 per week outside term-time, "
            "excluding VAT)."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "GBP")
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
    parser = argparse.ArgumentParser(description="CRASSH Cambridge connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  CRASSH (Cambridge) — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  CRASSH (Cambridge): {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
