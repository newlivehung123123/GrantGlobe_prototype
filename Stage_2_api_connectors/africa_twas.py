#!/usr/bin/env python3
"""
TWAS (The World Academy of Sciences) connector — Africa-relevant
programmes.

TWAS, headquartered in Trieste, Italy and operated in partnership with
UNESCO, supports scientists across the developing world broadly. This
connector covers TWAS's two flagship general programmes (open to
researchers from any developing country, including across Africa) plus
three programmes explicitly targeting African researchers:

1. TWAS Research Grants Programme in Basic Sciences — for individual
   scientists in developing countries to purchase equipment and
   consumables for their research.

2. TWAS Fellowships for Research and Advanced Training — for young
   scientists in developing countries to spend 3-12 months at a research
   institution in a developing country other than their own.

3. UNESCO-TWAS Seed Grant for New African Principal Investigators
   (SG-NAPI) — supported by Germany's Federal Ministry of Research,
   Technology and Space, for early-career researchers (40 or younger)
   who obtained their PhD abroad and have recently returned, or will
   shortly return, to an academic position in an African country
   identified by TWAS as lagging in science and technology.

4. TWAS-Mohammad A. Hamdan Award — biennial award for outstanding
   mathematical work by a scientist living and working in Africa or the
   Arab region.

5. TWAS-Abdool Karim Award in Biological Sciences — honours women
   scientists in Least Developed African countries.

(TWAS also runs numerous additional fellowships, awards, and visiting
scientist schemes for the developing world generally — PhD Fellowships,
Postdoctoral Fellowships, TWAS-CUI Fellowships hosted in Pakistan, and
several other annual cash-prize awards — which are not all included here;
this connector focuses on the broadest general schemes plus those with
explicit African eligibility criteria.)

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://twas.org/opportunities
Portal: https://twas.org/opportunities

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/africa_twas.py [--dry-run]
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

FUNDER = "TWAS (The World Academy of Sciences)"
DOMAIN = "api_africa_twas"
BASE   = "https://twas.org/opportunities"

SCHEMES: list[dict] = [
    {
        "title":   "TWAS Research Grants Programme in Basic Sciences",
        "url":     "https://twas.org/opportunities/research-and-project-grants",
        "portal":  BASE,
        # Annual deadline: 30 June.
        "deadline": datetime.date(2026, 6, 30),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher", "Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Africa", "Global South"],
        "focus_countries": [],
        "desc": (
            "The TWAS Research Grants Programme in Basic Sciences funds "
            "individual scientists based in developing countries — "
            "including across Africa — to purchase specialised "
            "equipment and consumable supplies for their research, and "
            "to support Master of Science students. The annual "
            "application deadline is 30 June; subsequent cycles follow "
            "a similar annual schedule. Full guidelines are published "
            "at https://twas.org/opportunities/research-and-project-"
            "grants."
        ),
    },
    {
        "title":   "TWAS Fellowships for Research and Advanced Training",
        "url":     "https://twas.org/opportunity/twas-fellowships-research-and-advanced-training",
        "portal":  BASE,
        # Annual deadline: 30 June.
        "deadline": datetime.date(2026, 6, 30),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions": ["Africa", "Global South"],
        "focus_countries": [],
        "desc": (
            "TWAS Fellowships for Research and Advanced Training enable "
            "young scientists from developing countries — including "
            "across Africa — to spend three to 12 months at a research "
            "institution in a developing country other than their own, "
            "gaining advanced training and research experience. The "
            "annual application deadline is 30 June; subsequent cycles "
            "follow a similar annual schedule. Full guidelines are "
            "published at https://twas.org/opportunities/fellowships."
        ),
    },
    {
        "title":   "UNESCO-TWAS Seed Grant for New African Principal Investigators (SG-NAPI)",
        "url":     "https://twas.org/opportunity/seed-grant-new-african-principal-investigators-sg-napi",
        "portal":  BASE,
        # 2026 cycle deadline: 31 March 2026 (already closed at authoring
        # time).
        "deadline": datetime.date(2026, 3, 31),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Seed Grant"],
        "individual": ["Early Career Researcher"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "USD",
        "sectors": [
            "Agriculture", "Biology", "Chemistry", "Earth Sciences",
            "Engineering", "Information Technology", "Mathematics",
            "Health Sciences", "Physics",
        ],
        "applicant_countries": [],
        "focus_regions": ["Africa"],
        "focus_countries": [],
        "desc": (
            "The UNESCO-TWAS Seed Grant for New African Principal "
            "Investigators (SG-NAPI), supported by Germany's Federal "
            "Ministry of Research, Technology and Space (BMFTR), "
            "strengthens the capacity of African countries identified "
            "by TWAS as lagging in science and technology. It targets "
            "early-career researchers who obtained their PhD abroad and "
            "have recently returned, or will shortly return, to an "
            "academic position in their home country. Eligibility "
            "requires the principal investigator to be 40 years old or "
            "younger, to have obtained their PhD within the last 5 "
            "years in a country other than their home country, to have "
            "returned home within the last 36 months (or to return "
            "before the end of the relevant year), and to be a national "
            "of an eligible African country. Grants support high-level "
            "research projects in agriculture, biology, chemistry, "
            "earth sciences, engineering, information and computer "
            "technology, mathematics, medical sciences, and physics. "
            "The 2026 cycle's deadline was 31 March 2026; subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://twas.org/opportunity/seed-grant-"
            "new-african-principal-investigators-sg-napi."
        ),
    },
    {
        "title":   "TWAS-Mohammad A. Hamdan Award",
        "url":     "https://twas.org/opportunity/twas-mohammad-hamdan-award",
        "portal":  BASE,
        # 2026 deadline: 30 June 2026 (biennial award).
        "deadline": datetime.date(2026, 6, 30),
        "open_threshold_days": 90,
        "cycle_years": 2,
        "grant_types": ["Award", "Prize"],
        "individual": ["Senior Researcher"],
        "org_types": [],
        "amount_min": 5000,
        "amount_max": 5000,
        "currency": "USD",
        "sectors": ["Mathematics"],
        "applicant_countries": [],
        "focus_regions": ["Africa"],
        "focus_countries": [],
        "desc": (
            "The TWAS-Mohammad A. Hamdan Award, established in 2020 and "
            "supported by a donation from the late TWAS Vice-President "
            "for the Arab Region, is a biennial award given for "
            "outstanding mathematical work carried out by a scientist "
            "living and working in Africa or the Arab region. The "
            "award is worth US$5,000. The 2026 deadline is 30 June "
            "2026; the award recurs every two years. Full guidelines "
            "are published at https://twas.org/opportunity/twas-"
            "mohammad-hamdan-award."
        ),
    },
    {
        "title":   "TWAS-Abdool Karim Award in Biological Sciences",
        "url":     "https://twas.org/opportunity/twas-abdool-karim-award-biological-sciences",
        "portal":  BASE,
        # Annual deadline: 30 June.
        "deadline": datetime.date(2026, 6, 30),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Award", "Prize"],
        "individual": ["Senior Researcher"],
        "org_types": [],
        "amount_min": 5000,
        "amount_max": 5000,
        "currency": "USD",
        "sectors": ["Biological Sciences"],
        "applicant_countries": [],
        "focus_regions": ["Africa"],
        "focus_countries": [],
        "desc": (
            "The TWAS-Abdool Karim Award in Biological Sciences, "
            "sponsored by TWAS President Professor Quarraisha Abdool "
            "Karim, honours women scientists in Least Developed African "
            "countries for their achievements in biological sciences. "
            "It carries a cash award of US$5,000. The annual "
            "application/nomination deadline is 30 June; subsequent "
            "cycles follow a similar annual schedule. Full guidelines "
            "are published at https://twas.org/opportunity/twas-"
            "abdool-karim-award-biological-sciences."
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
    cur.execute(
        "SELECT id FROM grants WHERE source_url = %s AND grant_title = %s",
        (db_rec["source_url"], db_rec["grant_title"]),
    )
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
    parser = argparse.ArgumentParser(description="TWAS connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  TWAS — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  TWAS: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
