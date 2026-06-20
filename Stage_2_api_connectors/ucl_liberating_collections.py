#!/usr/bin/env python3
"""
Liberating the Collections Fellowship (UCL Research Institute for
Collections) connector.

The Liberating the Collections Fellowship is an annual, six-week (or
part-time equivalent) residential research fellowship at UCL's Bloomsbury
campus, intended "to unearth underrepresented voices and find new ways of
engaging with collection stories and presenting them to wider society"
through UCL Museums Collections and/or UCL Special Collections. The
official eligibility section states plainly: "The Fellowship is open to
applicants of any nationality or career stage; from registered doctoral
candidates to senior scholars, creative practitioners, collections
professionals and independent researchers. Groups and communities of
interest will also be considered" — i.e. there is no PhD or university-
affiliation requirement of any kind; non-academic creative practitioners,
collections professionals, and independent researchers may apply directly
on the same footing as academics. The only practical constraint is the
standard UK right-to-work check (UCL does not sponsor visas for this
fellowship).

This mirrors the eligibility profile of other practitioner/independent-
researcher residencies already in this pipeline (e.g. Lewis Walpole
Library at Yale, CRASSH at Cambridge), with the distinguishing feature
that the Fellowship's own published criteria explicitly name "creative
practitioners," "collections professionals," and "independent researchers"
alongside doctoral candidates and senior scholars as equally eligible
applicant categories.

The official page confirms a £5,000 grant, workspace on the Bloomsbury
campus, and mediated collections access; required outputs include a
public-facing digital output (blog post, podcast, or event recording) plus
"an output of their choice in any format," which may be "academic as well
as creative ... including, but not limited to, a community project or a
piece of art or music."

The most recently confirmed annual deadline was "11:59pm Monday 12 January
2026" (curator-enquiry deadline 12 December 2025; notification by early
May 2026; projects starting from July 2026). This date has already passed
as of this connector's construction. The Fellowship has now recurred on an
annual basis across at least three consecutive cycles (5 Feb 2024 → 6 Jan
2025 → 12 Jan 2026), so the deadline is advanced by one annual cycle
(cycle_years=1) under this pipeline's standard convention.

Source: https://www.ucl.ac.uk/research-institute-collections/activities/fellowships/liberating-collections-fellowship

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/ucl_liberating_collections.py [--dry-run]
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

FUNDER = "Liberating the Collections Fellowship (UCL Research Institute for Collections)"
DOMAIN = "api_ucl_liberating_collections"
SOURCE_URL = "https://www.ucl.ac.uk/research-institute-collections/activities/fellowships/liberating-collections-fellowship"
PORTAL_URL = "mailto:ric-forms@ucl.ac.uk"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Liberating the Collections Fellowship",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "The deadline for applications is 11:59pm Monday 12
        # January 2026." Already passed at construction.
        "deadline":   datetime.date(2026, 1, 12),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": 5000,
        "amount_max": 5000,
        "sectors":    ["Cultural Heritage", "Museum & Archive Studies", "Public Engagement"],
        "individual": ["Practitioner", "Independent Researcher", "Researcher"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A six-week (or part-time equivalent) residential research "
            "fellowship at UCL's Bloomsbury campus, intended 'to unearth "
            "underrepresented voices and find new ways of engaging with "
            "collection stories and presenting them to wider society' "
            "through UCL Museums Collections and/or UCL Special "
            "Collections. Suggested (non-exhaustive) research areas "
            "include curating equality, contested histories, empire, "
            "decolonising natural history collections, disability, the "
            "ethics of collecting, power and social justice, and LGBTQ+ "
            "stories. The official eligibility section states: 'The "
            "Fellowship is open to applicants of any nationality or "
            "career stage; from registered doctoral candidates to senior "
            "scholars, creative practitioners, collections professionals "
            "and independent researchers. Groups and communities of "
            "interest will also be considered' — there is no PhD or "
            "university-affiliation requirement of any kind. The Fellow "
            "receives a grant of £5,000, workspace on the Bloomsbury "
            "campus, and mediated access to the collections, and is "
            "required to produce a public-facing digital output (a blog "
            "post, podcast, or event recording) plus 'an output of their "
            "choice in any format,' which may be academic or creative, "
            "'including, but not limited to, a community project or a "
            "piece of art or music.' UK right-to-work checks apply; UCL "
            "does not sponsor visa applications for this fellowship."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "GBP")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", [])
    _s.setdefault("focus_countries", ['GB'])


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
    parser = argparse.ArgumentParser(description="UCL Liberating the Collections Fellowship connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  UCL Liberating the Collections Fellowship — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  UCL Liberating the Collections Fellowship: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
