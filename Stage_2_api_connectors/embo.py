#!/usr/bin/env python3
"""
European Molecular Biology Organisation (EMBO) connector.

EMBO is an international organisation based in Heidelberg, Germany, that
supports excellence in the life sciences through fellowships, grants, and
career development programmes for researchers across Europe and beyond.
It is funded by the European Molecular Biology Conference (EMBC) and serves
researchers in more than 30 member and partner countries worldwide.

This connector covers four programmes with publicly open applications:

1. EMBO Postdoctoral Fellowships
   Two-year fellowships for internationally mobile postdoctoral researchers.
   Biannual submission cutoffs (~fourth Friday of January and ~10 July).
   Next cutoff: 10 July 2026, 14:00 CEST.

2. EMBO Young Investigator Programme (YIP)
   Four-year support package for group leaders within four years of their
   first independent position. Annual deadline: 1 April.

3. EMBO Installation Grants
   Research funding for group leaders establishing laboratories in
   participating EMBC countries (Croatia, Czechia, Estonia, Hungary,
   Lithuania, Luxembourg, Poland, Portugal, Türkiye). Annual deadline: 15 April.

4. EMBO Scientific Exchange Grants
   Funds short research visits (up to 3 months) between eligible countries.
   Rolling applications accepted throughout the year; no fixed deadline.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/embo.py [--dry-run]
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

FUNDER  = "European Molecular Biology Organisation (EMBO)"
DOMAIN  = "api_embo"
BASE    = "https://www.embo.org/funding/fellowships-grants-and-career-support"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. EMBO Postdoctoral Fellowships ─────────────────────────────────
        "title":    "EMBO Postdoctoral Fellowships",
        "url":      f"{BASE}/postdoctoral-fellowships/",
        "portal":   "http://applications.embo.org/01/register.php?reg=S019",
        "deadline": datetime.date(2026, 7, 10),      # next Autumn cutoff (14:00 CEST)
        "open_threshold_days": 366,                   # rolling; always open
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  ["University", "Research Institution", "Medical School"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "EUR",
        "sectors": [
            "Life Sciences", "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries":  [],
        "focus_regions":        ["Europe", "Global"],
        "focus_countries":      [],
        "desc": (
            "EMBO Postdoctoral Fellowships support excellent postdoctoral researchers "
            "in the life sciences for up to two years. International mobility is a "
            "key requirement: applicants must relocate to a different country for "
            "their fellowship. The award includes a salary or stipend set according "
            "to host country rates, a relocation allowance, and financial support "
            "for fellows with children. Awardees may attend an EMBO Laboratory "
            "Leadership course and join the global EMBO Fellows network. "
            "Applications from researchers at institutions in EMBC Member States and "
            "approved partner countries worldwide are eligible. EMBO treats a first-"
            "author refereed preprint as equivalent to a first-author publication for "
            "eligibility and assessment purposes. "
            "Applications are accepted throughout the year, with biannual hard cutoff "
            "dates for selection: the Spring round closes on the fourth Friday of "
            "January (14:00 CET) and the Autumn round closes on or around "
            "10 July (14:00 CEST). Starting from the Autumn 2026 round, a host "
            "laboratory may support a maximum of one candidate per selection round. "
            "The next cutoff date is 10 July 2026, 14:00 CEST."
        ),
    },
    {
        # ── 2. EMBO Young Investigator Programme ─────────────────────────────
        "title":    "EMBO Young Investigator Programme",
        "url":      f"{BASE}/young-investigator-programme/",
        "portal":   "http://applications.embo.org/01/register.php?reg=P0M8",
        "deadline": datetime.date(2026, 4, 1),       # annual deadline
        "open_threshold_days": 90,                    # portal opens ~Jan
        "cycle_years": 1,
        "grant_types": ["Research Grant", "Fellowship"],
        "individual": ["Early Career Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "EUR",
        "sectors": [
            "Life Sciences", "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries":  [],
        "focus_regions":        ["Europe", "Global"],
        "focus_countries":      [],
        "desc": (
            "The EMBO Young Investigator Programme (YIP) supports early-career life "
            "scientists who have been group leaders for less than four years at the "
            "time of application. Young Investigators receive four years of financial "
            "support for networking and research activities, access to training and "
            "mentoring opportunities, and support for lab members. Awardees join an "
            "international network of more than 800 current and former EMBO Young "
            "Investigators, Installation Grantees, and Global Investigators. "
            "Applicants must hold an independent group leader position at a research "
            "institution in an EMBC Member State or approved partner country, and "
            "must have held their first independent group leader position for no more "
            "than four years at the time of application. "
            "Applications open each January and the annual deadline is 1 April. "
            "A pre-application form is available on the EMBO website."
        ),
    },
    {
        # ── 3. EMBO Installation Grants ──────────────────────────────────────
        "title":    "EMBO Installation Grants",
        "url":      f"{BASE}/installation-grants/",
        "portal":   "http://applications.embo.org/01/register.php?reg=58UW",
        "deadline": datetime.date(2026, 4, 15),      # annual deadline
        "open_threshold_days": 90,                    # portal opens ~Jan
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Early Career Researcher", "Mid-Career Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "EUR",
        "sectors": [
            "Life Sciences", "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries":  [],
        "focus_regions":        ["Europe"],
        # Host countries participating in the 2026 scheme
        "focus_countries":      ["HR", "CZ", "EE", "HU", "LT", "LU", "PL", "PT", "TR"],
        "desc": (
            "EMBO Installation Grants support group leaders who are establishing "
            "laboratories in countries participating in the Installation Grant "
            "scheme, with the aim of strengthening life sciences research capacity "
            "in those countries. In the 2026 call, grants are available to group "
            "leaders establishing laboratories in Croatia, Czechia, Estonia, Hungary, "
            "Lithuania, Luxembourg, Poland, Portugal, and Türkiye. Applicants need "
            "not be nationals of the host country. "
            "Installation Grantees join an international network of more than 800 "
            "current and former EMBO Young Investigators, Installation Grantees, "
            "and Global Investigators, and benefit from associated training and "
            "networking opportunities. "
            "Applications open in January each year. The annual deadline is "
            "15 April. Participating countries may change between annual calls."
        ),
    },
    {
        # ── 4. EMBO Scientific Exchange Grants ───────────────────────────────
        "title":    "EMBO Scientific Exchange Grants",
        "url":      f"{BASE}/scientific-exchange-grants/",
        "portal":   "https://applications.embo.org/register.php?reg=80DN",
        # Rolling programme — set a far-future sentinel date so the record
        # is always "Open". _advance_deadline will advance by cycle_years=4
        # once the sentinel passes, keeping the status perpetually open.
        "deadline": datetime.date(2030, 12, 31),
        "open_threshold_days": 1700,                  # always open (rolling)
        "cycle_years": 4,
        "grant_types": ["Travel Grant", "Research Grant"],
        "individual": ["Graduate Student", "Postdoctoral Researcher",
                       "Early Career Researcher", "Mid-Career Researcher",
                       "Senior Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": 6500,
        "currency":   "EUR",
        "sectors": [
            "Life Sciences", "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries":  [],
        "focus_regions":        ["Europe", "Global"],
        "focus_countries":      [],
        "desc": (
            "EMBO Scientific Exchange Grants fund short research visits of up to "
            "three months between laboratories in eligible countries. The grants "
            "facilitate international collaborations by enabling the transfer of "
            "expertise and techniques, or access to infrastructure unavailable in "
            "the applicant's home laboratory. Awards cover travel costs and "
            "subsistence expenses for the duration of the visit (up to EUR 6,500 "
            "for longer visits; amounts depend on destination country and duration). "
            "Applicants must be researchers — from PhD students to senior scientists "
            "— affiliated with an institution in an EMBC Member State or approved "
            "partner country. The host laboratory must be in an eligible country "
            "different from the applicant's home institution. "
            "Applications are accepted on a rolling basis throughout the year with "
            "no fixed submission deadline. Decisions are typically communicated "
            "within four to six weeks of submission."
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
        "application_deadline_raw":  f"{deadline.day} {deadline.strftime('%B %Y')}",
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
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    db_rec = {k: v for k, v in record.items() if not k.startswith("_")}
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s", (db_rec["source_url"],))
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
    parser = argparse.ArgumentParser(description="EMBO connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  EMBO — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  EMBO: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
