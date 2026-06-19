#!/usr/bin/env python3
"""
Lee Kong Chian NUS-Stanford Fellowship in Contemporary Southeast Asia
(National University of Singapore Faculty of Arts and Social Sciences /
Stanford Shorenstein Asia-Pacific Research Center) connector.

The Lee Kong Chian Fellowship is the core of the Lee Kong Chian NUS-Stanford
Initiative on Southeast Asia, a joint effort established in 2007 by NUS and
Stanford University "to raise the visibility, extent, and quality of
scholarship on contemporary Southeast Asia." One or two Fellows are selected
each year to spend three to four months at Stanford and three to four months
at NUS writing and conducting research on contemporary Southeast Asia. The
official eligibility statement reads plainly: "Interested individuals with
professional backgrounds and current, ongoing professional positions related
to the social sciences or humanities are encouraged to apply. Candidates may
be of any nationality or seniority" — i.e. there is no PhD or university-
affiliation requirement of any kind; working professionals in ongoing,
non-academic positions are explicitly invited to apply on the same footing as
academic scholars, regardless of seniority. This is independently corroborated
by the Fellowship's own alumni record, which lists at least one historical
Fellow (2016-17) credited simply as "Independent Scholar and International
Development Consultant" with no university affiliation at all.

This mirrors the eligibility profile of other practitioner-inclusive
fellowships already in this pipeline (e.g. CASI at UPenn, AFSEE at LSE), with
the distinguishing feature that the Fellowship's own published eligibility
statement waives any seniority or career-stage requirement entirely, framing
"any nationality or seniority" as the sole qualifying criterion alongside an
ongoing professional or scholarly engagement with Southeast Asia.

The Fellowship provides a stipend of US$8,000 per month for the duration of
the appointment (three to four months at each campus, six to eight months
total), plus two separate roundtrip economy-class airfares (one between the
Fellow's home country and NUS, one between the home country and Stanford).

The official Stanford programme page confirms: "The 2025-26 Lee Kong Chian
NUS-Stanford Fellowship accepts applications from August 7, 2024, through
January 24, 2025... Application must be received via email by January 24,
2025." This date has already passed as of this connector's construction. The
programme has run continuously since 2007, with a documented unbroken annual
Fellow cohort from 2008-9 through 2025-26 (eighteen consecutive cycles), so
the deadline is advanced by one annual cycle (cycle_years=1) under this
pipeline's standard convention. As of construction, the Fellowship is listed
as "currently closed for applications," with the next cycle's call expected
to be posted in fall 2026 — consistent with the established annual pattern.

Source: https://aparc.fsi.stanford.edu/education/fellowship-and-training-opportunities/nus-stanford-fellowship-southeast-asia
NUS programme page: https://fass.nus.edu.sg/visiting-appointments/lee-kong-chian-distinguished-fellowship-overview/the-lee-kong-chian-distinguished-fellowship-application/
Apply (email): nusstanfordsea@nus.edu.sg and kilimpan@stanford.edu

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/nus_lee_kong_chian.py [--dry-run]
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

FUNDER = "Lee Kong Chian NUS-Stanford Fellowship in Contemporary Southeast Asia (National University of Singapore / Stanford University)"
DOMAIN = "api_nus_lee_kong_chian"
SOURCE_URL = "https://aparc.fsi.stanford.edu/education/fellowship-and-training-opportunities/nus-stanford-fellowship-southeast-asia"
PORTAL_URL = "https://fass.nus.edu.sg/visiting-appointments/lee-kong-chian-distinguished-fellowship-overview/the-lee-kong-chian-distinguished-fellowship-application/"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Lee Kong Chian NUS-Stanford Fellowship in Contemporary Southeast Asia",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "Application must be received via email by January 24,
        # 2025." Already passed at construction.
        "deadline":   datetime.date(2025, 1, 24),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": 8000,
        "amount_max": 8000,
        "sectors":    ["Southeast Asian Studies", "Social Sciences", "Humanities", "Area Studies"],
        "individual": ["Practitioner", "Independent Researcher", "Researcher", "Policymaker"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": ["Southeast Asia"],
        "focus_countries": [],
        "desc": (
            "A joint fellowship of the National University of Singapore "
            "(Faculty of Arts and Social Sciences) and Stanford "
            "University's Walter H. Shorenstein Asia-Pacific Research "
            "Center, at the core of the Lee Kong Chian NUS-Stanford "
            "Initiative on Southeast Asia (established 2007). One or two "
            "Fellows are selected each year to spend three to four months "
            "at Stanford and three to four months at NUS writing and "
            "conducting research on contemporary Southeast Asia. The "
            "official eligibility statement reads: 'Interested "
            "individuals with professional backgrounds and current, "
            "ongoing professional positions related to the social "
            "sciences or humanities are encouraged to apply. Candidates "
            "may be of any nationality or seniority' — there is no PhD or "
            "university-affiliation requirement of any kind; the "
            "Fellowship's own alumni record lists at least one historical "
            "Fellow (2016-17) credited simply as 'Independent Scholar and "
            "International Development Consultant.' The Fellowship "
            "provides a stipend of US$8,000 per month for the full "
            "six-to-eight-month appointment, plus two separate roundtrip "
            "economy-class airfares (one between the Fellow's home "
            "country and NUS, one between the home country and "
            "Stanford). Required application materials: a project "
            "statement (max. three pages), a proposed residence "
            "schedule, a sample of published English-language work, a "
            "full CV, and contact information for three academic "
            "referees, sent by email simultaneously to NUS and Stanford."
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
    parser = argparse.ArgumentParser(description="NUS Lee Kong Chian NUS-Stanford Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  NUS Lee Kong Chian NUS-Stanford Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  NUS Lee Kong Chian NUS-Stanford Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
