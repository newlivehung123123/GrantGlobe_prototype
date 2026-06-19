#!/usr/bin/env python3
"""
Atlantic Fellows for Social and Economic Equity (AFSEE) — London School of
Economics and Political Science, International Inequalities Institute —
connector.

AFSEE is one of seven global Atlantic Fellows programmes (funded by a
£64 million, 20-year grant from Atlantic Philanthropies) and is aimed at
"mid-career social-change leaders who have at least seven years of
experience in challenging inequalities." The official news release on the
current cohort states plainly: "Policymakers, researchers, activists,
practitioners, artists, and movement-builders from around the world are
invited to apply to the innovative, fully-funded, and inequalities-focused
fellowship programme" — i.e. there is no PhD or university-affiliation
requirement of any kind; non-academic activists, practitioners, artists,
and movement-builders may apply directly on the same footing as
researchers and policymakers. Applicants may work in any field of social
and economic equity, "including, but not limited to economic and social
rights; sustainability and environmental justice; tax justice and economic
alternatives; women's, minority, and disability rights; rights to
education; public policy; housing and urban inequalities; labour rights;
community organising; arts and culture; and peacebuilding and transitional
justice."

This mirrors the eligibility profile of other practitioner-inclusive
fellowships already in this pipeline (e.g. UCL Liberating the Collections,
Mila AI Policy Fellowship), with the distinguishing feature that AFSEE's
own published criteria name "activists," "practitioners," "artists," and
"movement-builders" alongside researchers and policymakers as equally
eligible applicant categories, with a 7-years'-experience threshold
substituting for any academic credential requirement.

The Fellowship offers two tracks: Residential Fellows spend one year in
London undertaking the MSc in Inequalities and Social Science at LSE plus
four bespoke fellowship modules; Non-Residential Fellows remain in their
home countries, develop a practice-based project, join the fellowship
modules online/in-person, and receive a Postgraduate Certificate in Social
and Economic Equity on completion. Both tracks are fully funded (no
stipend or tuition figure is separately disclosed on the public pages).
After the active fellowship year, Fellows join a global community of up to
400 Atlantic Fellows across all seven programmes and gain access to
follow-on funding and collaborative opportunities as Senior Fellows.

The official news release confirms: "Applications for the 2026-27 Cohort
will close at 5pm (UK time) on 16 January 2026" — this date has already
passed as of this connector's construction. Launched in 2016 and now
recruiting its tenth consecutive cohort, the programme has recurred
annually for ten straight cycles, so the deadline is advanced by one
annual cycle (cycle_years=1) under this pipeline's standard convention.

Source: https://afsee.atlanticfellows.lse.ac.uk/en-gb/news/applications-open-for-the-2026-27-cohort
Programme overview: https://www.lse.ac.uk/international-inequalities/atlantic-fellows-programme
Apply: https://afsee.atlanticfellows.lse.ac.uk/en-gb/apply

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/lse_afsee.py [--dry-run]
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

FUNDER = "Atlantic Fellows for Social and Economic Equity (London School of Economics)"
DOMAIN = "api_lse_afsee"
SOURCE_URL = "https://afsee.atlanticfellows.lse.ac.uk/en-gb/news/applications-open-for-the-2026-27-cohort"
PORTAL_URL = "https://afsee.atlanticfellows.lse.ac.uk/en-gb/apply"
ORG_NONE: list[str] = []

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "Atlantic Fellows for Social and Economic Equity (AFSEE)",
        "url":      SOURCE_URL,
        "portal":   PORTAL_URL,
        # Sourced: "Applications for the 2026-27 Cohort will close at 5pm
        # (UK time) on 16 January 2026." Already passed at construction.
        "deadline":   datetime.date(2026, 1, 16),
        "cycle_years": 1,
        "open_threshold_days": 90,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Social Equity", "Economic Inequality", "Public Policy", "Social Justice"],
        "individual": ["Practitioner", "Activist", "Policymaker", "Researcher", "Artist"],
        "grant_types": ["Fellowship"],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": [],
        "desc": (
            "A fully-funded fellowship for mid-career social-change "
            "leaders, based at the International Inequalities Institute "
            "at the London School of Economics and Political Science, "
            "and one of seven global Atlantic Fellows programmes funded "
            "by a £64 million, 20-year grant from Atlantic "
            "Philanthropies. The official news release states: "
            "'Policymakers, researchers, activists, practitioners, "
            "artists, and movement-builders from around the world are "
            "invited to apply' — there is no PhD or university-"
            "affiliation requirement of any kind. Eligible applicants "
            "must have 'at least seven years of experience in "
            "challenging inequalities' in any field of social and "
            "economic equity, including but not limited to economic and "
            "social rights; sustainability and environmental justice; "
            "tax justice and economic alternatives; women's, minority, "
            "and disability rights; rights to education; public policy; "
            "housing and urban inequalities; labour rights; community "
            "organising; arts and culture; and peacebuilding and "
            "transitional justice. Residential Fellows spend one year in "
            "London undertaking the MSc in Inequalities and Social "
            "Science at LSE alongside four bespoke fellowship modules; "
            "Non-Residential Fellows remain in their home countries, "
            "develop a practice-based project, join the fellowship "
            "modules online and in person, and receive a Postgraduate "
            "Certificate in Social and Economic Equity on completion. "
            "Both tracks are fully funded. Launched in 2016 with a goal "
            "of building a 400-strong global community over two "
            "decades, the programme is now recruiting its tenth "
            "consecutive annual cohort; on completion, Fellows join the "
            "wider Atlantic Fellows community across all seven global "
            "programmes and gain access to follow-on funding as Senior "
            "Fellows."
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
    parser = argparse.ArgumentParser(description="LSE Atlantic Fellows for Social and Economic Equity connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  LSE Atlantic Fellows for Social and Economic Equity — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  LSE Atlantic Fellows for Social and Economic Equity: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
