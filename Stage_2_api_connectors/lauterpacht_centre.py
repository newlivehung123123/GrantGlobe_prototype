#!/usr/bin/env python3
"""
Lauterpacht Centre for International Law (University of Cambridge) —
Visitor Programme connector.

The Lauterpacht Centre accepts visiting applications from PhD candidates,
academics from other institutions, AND professional individuals — i.e.
the programme is explicitly open to non-academics, not restricted to
scholars. Visitors are self-funded (the Centre provides no financial
assistance) but gain access to the Centre's facilities, lectures, and
events for one of three termly intake windows per academic year.

The source page's published table states three exact upcoming deadlines:
"Michaelmas Term 2026 | 10 April 2026", "Lent Term 2027 | 4 September
2026", and "Easter Term 2027/Summer Research Period 2027 | 11 December
2026." The Michaelmas Term 2026 deadline has already passed as of this
connector's construction, so it is advanced by one annual cycle
(cycle_years=1) under this pipeline's standard convention; the Lent Term
2027 and Easter Term 2027 deadlines are still in the future and are used
as sourced.

Source: https://www.lcil.cam.ac.uk/visitors/how-apply

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/lauterpacht_centre.py [--dry-run]
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

FUNDER = "Lauterpacht Centre for International Law (University of Cambridge)"
DOMAIN = "api_lauterpacht_centre"
SOURCE_URL = "https://www.lcil.cam.ac.uk/visitors/how-apply"
PORTAL_URL = "https://www.lcil.cam.ac.uk/files/images/www.lcil.law.cam.ac.uk/Documents/VFInformation/lcil_visitor_application_form.docx"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title": "Lauterpacht Centre Visitor Programme — Michaelmas Term",
        # Sourced exactly: "10 April 2026" (for Michaelmas Term 2026 arrival).
        "deadline": datetime.date(2026, 4, 10),
    },
    {
        "title": "Lauterpacht Centre Visitor Programme — Lent Term",
        # Sourced exactly: "4 September 2026" (for Lent Term 2027 arrival).
        "deadline": datetime.date(2026, 9, 4),
    },
    {
        "title": "Lauterpacht Centre Visitor Programme — Easter Term / Summer Research Period",
        # Sourced exactly: "11 December 2026" (for Easter Term/Summer
        # Research Period 2027 arrival).
        "deadline": datetime.date(2026, 12, 11),
    },
]

for _s in SCHEMES:
    _s.setdefault("url", SOURCE_URL)
    _s.setdefault("portal", PORTAL_URL)
    _s.setdefault("cycle_years", 1)
    _s.setdefault("open_threshold_days", 90)
    _s.setdefault("amount_min", None)
    _s.setdefault("amount_max", None)
    _s.setdefault("sectors", ["International Law"])
    _s.setdefault("individual", ["Researcher", "Faculty", "Doctoral Student", "Practitioner"])
    _s.setdefault("grant_types", ["Fellowship"])
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "GBP")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])
    _s.setdefault("focus_countries", ['GB'])
    _s.setdefault("desc", (
        "A self-funded visiting placement at Cambridge's Lauterpacht "
        "Centre for International Law, with applications considered "
        "once per term by the Centre's Committee of Management. The "
        "Centre explicitly accepts applications from students "
        "completing PhD work, academics from other institutions, and "
        "professional individuals — not restricted to academics. "
        "Visitors must support themselves for the duration of their "
        "stay (the Centre provides no financial assistance) and gain "
        "access to open lectures and events at the Centre and, by "
        "arrangement, elsewhere in the University. A good standard of "
        "English (broadly equivalent to IELTS 7.5) is required, and the "
        "Centre does not accept persons already enrolled for higher "
        "degrees at UK universities."
    ))


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
    parser = argparse.ArgumentParser(description="Lauterpacht Centre connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Lauterpacht Centre — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Lauterpacht Centre: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
