#!/usr/bin/env python3
"""
Gerald Loeb Awards (UCLA Anderson School of Management) connector.

The Gerald Loeb Awards are the most prestigious honor in business
journalism in the United States, established in 1957 and administered by
UCLA Anderson School of Management. Across thirteen competition
categories, the official Eligibility & Rules page states plainly: "Any
journalist or media outlet (print, digital, television, radio, streaming,
news apps, blogs/newsletters or social) may enter submissions on a
subject related to business, finance and economics," and confirms
"Individual authors may submit a maximum of two (2) submissions" —
i.e. freelance and independent journalists may enter directly, with no
PhD, university affiliation, citizenship, or residency requirement of any
kind. The only content-based restriction is that submissions "must have
been published or broadcast in the United States" during the relevant
calendar year — a publication-venue requirement, not a nationality
requirement on the journalist. Each category winner receives a cash
prize of $2,000, presented at an annual awards ceremony; there is a
$100 per-submission entry fee for the journalism competition categories
(Career Achievement nominations are free).

The official "2026 Call for Entries" ran "March 17 - April 30," with
entries covering work "published or broadcast in the United States in
the calendar year 2025." The April 30, 2026 deadline has already passed
as of this connector's construction. The competition recurs annually on
this same March-opening/April-closing pattern, so the deadline is
advanced by one annual cycle (cycle_years=1) under this pipeline's
standard convention.

Source: https://www.anderson.ucla.edu/news-and-events/signature-events/gerald-loeb-awards
Eligibility & Rules: https://www.anderson.ucla.edu/news-and-events/signature-events/gerald-loeb-awards/eligibility-and-rules

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/ucla_gerald_loeb.py [--dry-run]
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

FUNDER = "Gerald Loeb Awards (UCLA Anderson School of Management)"
DOMAIN = "api_ucla_gerald_loeb"
SOURCE_URL = "https://www.anderson.ucla.edu/news-and-events/signature-events/gerald-loeb-awards"
PORTAL_URL = "https://loeb.awardsplatform.com/"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Gerald Loeb Awards — Journalism Competition",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "2026 CALL FOR ENTRIES: March 17 - April 30" for
        # submissions published/broadcast in the US in calendar year
        # 2025. Already passed at construction.
        "deadline":   datetime.date(2026, 4, 30),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": 2000,
        "amount_max": 2000,
        "sectors":    ["Business Journalism", "Financial Journalism", "Economics Reporting"],
        "individual": ["Journalist", "Practitioner"],
        "grant_types": ["Award"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["US"],  # CHAR(2)[] column — ISO-2 code, not full name
        "desc": (
            "The most prestigious honor in U.S. business journalism, "
            "established in 1957 by Gerald Loeb (a founding partner of "
            "E.F. Hutton) to encourage and support reporting on business "
            "and finance that informs and protects both private "
            "investors and the public. Thirteen competition categories "
            "span print, digital, television, radio, streaming, news "
            "apps, blogs/newsletters, and social formats, including "
            "audio, video, and graphics/interactives. The official "
            "Eligibility & Rules page states: 'Any journalist or media "
            "outlet ... may enter submissions on a subject related to "
            "business, finance and economics,' and confirms individual "
            "authors may submit directly (a maximum of two submissions "
            "each), with no PhD, university affiliation, citizenship, "
            "or residency requirement. The sole content restriction is "
            "that the submitted work must have been 'published or "
            "broadcast in the United States' during the relevant "
            "calendar year. Each category winner receives a $2,000 cash "
            "prize and is honored at an annual awards ceremony; entries "
            "carry a $100 per-submission fee (Career Achievement "
            "nominations, a separate honorary group, are free and may "
            "be submitted by organizations or individuals on behalf of "
            "a journalist or editor)."
        ),
    },
]

for _s in SCHEMES:
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
    parser = argparse.ArgumentParser(description="UCLA Gerald Loeb Awards connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  UCLA Gerald Loeb Awards — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  UCLA Gerald Loeb Awards: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
