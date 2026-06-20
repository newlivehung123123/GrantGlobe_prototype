#!/usr/bin/env python3
"""
Africa Oxford Initiative (AfOx, University of Oxford) — AfOx Visiting
Fellowship Programme connector.

The AfOx Visiting Fellowship Programme allows researchers based at African
academic or research institutions to spend a 12-month affiliation with the
University of Oxford (ten months of virtual engagement plus a two-month
in-person visit during Trinity term, typically May-June) collaborating
with an Oxford-based academic host. Fellowships are offered across more
than a dozen partner departments and centres (TORCH, Oxford Department of
International Development, the Law Faculty, the Mathematical Institute,
the Refugee Studies Centre, the African Studies Centre, the Ethox Centre,
Oxford EARTH, the Oxford Centre for Islamic Studies, Oxford Cancer,
WildCRU, and others), each with its own thematic focus.

The source page states exactly: "Applications are now Open... until 15th
May 2026." That date has already passed as of this connector's
construction, so it is advanced by one annual cycle (cycle_years=1) under
this pipeline's standard convention.

Eligibility is restricted to researchers of postdoctoral or equivalent
status holding an appointment at an African academic or research
institution (nationals of, or with indefinite leave to remain in, any
African country) — i.e. this scheme is academic-only, not open to
non-academic practitioners, unlike several of the Harvard-affiliated
schemes built earlier in this pipeline.

Source: https://www.afox.ox.ac.uk/research/afox_visiting_fellowship_programme

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/oxford_afox.py [--dry-run]
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

FUNDER = "Africa Oxford Initiative (University of Oxford)"
DOMAIN = "api_oxford_afox"
SOURCE_URL = "https://www.afox.ox.ac.uk/research/afox_visiting_fellowship_programme"
PORTAL_URL = "https://webportalapp.com/sp/afox-visiting-fellowship-application-2026"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "AfOx Visiting Fellowship Programme",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced exactly: "Applications are now Open... until 15th May 2026".
        "deadline":   datetime.date(2026, 5, 15),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Multidisciplinary", "African Studies", "Development Studies"],
        "individual": ["Researcher", "Post-doctoral Scholar", "Faculty"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": ["Africa"],
        "focus_countries": [],
        "desc": (
            "A 12-month fellowship affiliation with the University of "
            "Oxford for researchers based at African academic or "
            "research institutions, comprising ten months of virtual "
            "engagement and a two-month in-person visit to Oxford during "
            "Trinity term (May-June). Fellows are paired with an "
            "Oxford-based academic collaborator and hosted by one of "
            "over a dozen partner departments and centres, including "
            "TORCH, the Department of International Development, the Law "
            "Faculty, the Mathematical Institute, the Refugee Studies "
            "Centre, the African Studies Centre, the Ethox Centre "
            "(bioethics), Oxford EARTH, the Oxford Centre for Islamic "
            "Studies, Oxford Cancer, and WildCRU. Open to nationals of, "
            "or those with indefinite leave to remain in, any African "
            "country who hold postdoctoral or equivalent status at an "
            "African academic or research institution; not open to "
            "non-academic applicants. Funded benefits include return "
            "economy flights, in-person accommodation, visa-fee "
            "reimbursement, and a maintenance allowance of up to £250 "
            "per week during the Oxford residency."
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
    parser = argparse.ArgumentParser(description="AfOx Visiting Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  AfOx Visiting Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  AfOx Visiting Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
