#!/usr/bin/env python3
"""
University of Hong Kong (HKU) — Society of Fellows in the Humanities
connector.

Distinct from the Research Grants Council schemes covered in
hongkong_rgc.py, this is HKU's own institutional postdoctoral fellowship,
run by its Faculty of Arts to attract exceptional early-career humanities
scholars from around the world. Up to two Fellowships (appointed at the
rank of Research Assistant Professor) are awarded per annual intake for a
non-renewable three-year term.

Eligibility requires a PhD conferred within a defined window relative to
the appointment year, no current tenure-track position, and explicitly
excludes candidates who hold a PhD from HKU itself. Applications are
submitted in English via HKU's central careers site.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.sof.arts.hku.hk/call-for-applications
Portal: https://jobs.hku.hk/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/hongkong_hku.py [--dry-run]
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

FUNDER = "University of Hong Kong (HKU) — Society of Fellows in the Humanities"
DOMAIN = "api_hongkong_hku_sof"
BASE   = "https://www.sof.arts.hku.hk/call-for-applications"
PORTAL = "https://jobs.hku.hk/"

SCHEMES: list[dict] = [
    {
        "title":   "HKU Society of Fellows in the Humanities",
        "url":     BASE,
        "portal":  PORTAL,
        # 2026-2027 intake: deadline 28 February 2026 (already closed at
        # authoring time). Advances annually to the next intake.
        "deadline": datetime.date(2026, 2, 28),
        "open_threshold_days": 90,        # call typically opens several months prior
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher", "Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "HKD",
        "sectors": [
            "Humanities", "Social Sciences", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Hong Kong"],
        "desc": (
            "The Society of Fellows in the Humanities at the University "
            "of Hong Kong (HKU) invites applications from qualified "
            "early-career scholars worldwide for its annual intake. Up to "
            "two Fellowships (appointed at the rank of Research Assistant "
            "Professor) commence between June and August each year for a "
            "non-renewable three-year term. Eligible applicants must hold "
            "a PhD conferred within approximately the preceding two years "
            "of the appointment start (e.g. for the 2026-2027 intake, a "
            "PhD conferred after 1 January 2024 but not later than 30 "
            "June 2026), must not currently hold a tenure-track position, "
            "and — notably — candidates who hold a PhD from HKU itself "
            "are not eligible. Fellows receive a globally competitive "
            "package including monthly salary, medical benefits, annual "
            "leave, and conference and research support, and are expected "
            "to teach two courses during their appointment. HKU is an "
            "English-medium university and applications are submitted "
            "entirely in English, comprising a CV, a cover letter (under "
            "300 words), a research proposal (under 1,500 words), a "
            "writing sample, and three letters of recommendation. "
            "Applications are submitted only through HKU's central "
            "careers site at https://jobs.hku.hk/; the 2026-2027 intake's "
            "deadline was 28 February 2026, 23:00 Hong Kong time, with "
            "notification by the end of April 2026."
        ),
    },
    {
        # ── 2. HKU Presidential PhD Scholar Programme ─────────────────────────
        "title":    "HKU Presidential PhD Scholar Programme",
        "url":      "https://gradsch.hku.hk/prospective_students/fees_scholarships_and_financial_support/hku_presidential_phd_scholar_programme",
        "portal":   "https://rola.hku.hk/",
        # Main Round: 1 September - 1 December each year.
        "deadline": datetime.date(2026, 12, 1),
        "open_threshold_days": 95,        # Main Round opens 1 September
        "cycle_years": 1,
        "grant_types": ["PhD Scholarship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": 422000,
        "amount_max": 439500,
        "currency": "HKD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["Hong Kong"],
        "desc": (
            "The HKU Presidential PhD Scholar Programme (HKU-PS) offers "
            "the University of Hong Kong's most prestigious scholarship "
            "package to selected outstanding full-time PhD students "
            "worldwide, in order to attract top candidates to pursue "
            "full-time PhD studies at HKU. Scholars receive strong "
            "academic and training support, including individualised "
            "advisory service, teaching training, and mentorship from a "
            "group of distinguished faculty members who oversee their "
            "academic career path. The 2026/27 admission package is "
            "worth up to approximately HK$439,500 in the first year and "
            "up to approximately HK$422,000 in each subsequent year of "
            "the normative study period, comprising a cash award, "
            "composition-fee waiver, a postgraduate scholarship stipend "
            "of HK$28,400 per month, a conference and research travel "
            "allowance, possible additional funded study time, and a "
            "guaranteed first-year hall place. All applicants to HKU's "
            "full-time PhD programme are automatically considered for "
            "the HKU-PS Programme; no separate application is required "
            "beyond the standard PhD application. Applicants are "
            "strongly encouraged to apply during the Main Round (1 "
            "September to 1 December) given intense competition, and "
            "are advised to also apply for the Hong Kong PhD Fellowship "
            "Scheme (see hongkong_rgc.py) given the overlapping "
            "applicant pool. Shortlisted candidates may be invited to "
            "interview."
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
        "application_deadline_raw":  scheme.get(
            "deadline_raw", f"{deadline.day} {deadline.strftime('%B %Y')}"
        ),
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
    parser = argparse.ArgumentParser(description="HKU Society of Fellows connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  HKU Society of Fellows — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  HKU Society of Fellows: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
