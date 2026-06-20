#!/usr/bin/env python3
"""
Chinese Academy of Sciences (CAS) President's International Fellowship
Initiative (PIFI) connector.

PIFI is distinct from NSFC (see china_nsfc.py) — it is CAS's own fellowship
programme, not an NSFC research-grant scheme, and is documented in English
across CAS-affiliated institute websites. PIFI is open to international
scientific research personnel worldwide across four categories:
Distinguished Scientists (1-2 week lecture tours, ¥50,000/week stipend),
Visiting Scientists (1-12 month cooperative projects, monthly living-expense
stipend), Postdoctoral Researchers (¥200,000/year pre-tax stipend), and
International PhD Students (degree training at UCAS/USTC combined with
research at a CAS institute).

PIFI does not accept direct applications from foreign scientific research
staff: applicants must first identify a CAS host researcher at a
CAS-affiliated institution, who prepares and submits the application via
CAS's internal Academia Resource Planning (ARP) system on the applicant's
behalf, following institutional and CAS PIFI-management review. This is a
host-affiliated structure analogous to NSFC's RFIS programme, and consistent
with this project's general national-funder connectors. Applications are
explicitly accepted "all year round" and reviewed in batches (typically
within 3 months of submission) — a genuinely rolling call.

Source: http://english.iop.cas.cn/ju/pifi/
Portal: https://pifi.cas.cn/front/pc.html#/bicsite/home

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/china_cas_pifi.py [--dry-run]
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

FUNDER = "Chinese Academy of Sciences (CAS) — President's International Fellowship Initiative (PIFI)"
DOMAIN = "api_china_cas_pifi"
BASE   = "http://english.iop.cas.cn/ju/pifi/"
PORTAL = "https://pifi.cas.cn/front/pc.html#/bicsite/home"

DESC = (
    "The CAS President's International Fellowship Initiative (PIFI) is a "
    "funding programme designed to establish scientific cooperation and "
    "promote research communication between the Chinese Academy of "
    "Sciences (CAS) and the global research community. It is open to all "
    "scientific research personnel worldwide, covering scholars at "
    "different career stages from Nobel laureates to young master's "
    "students, across four main categories: (1) Distinguished Scientists — "
    "leading international scientists conducting a 1-2 week lecture tour "
    "across at least two CAS-affiliated institutions, with a stipend of "
    "¥50,000 per week covering airfare, accommodation, meals, "
    "transportation and honorarium; (2) Visiting Scientists — high-caliber "
    "international scientists carrying out cooperative research projects "
    "at CAS-affiliated institutions for 1-12 months, receiving a monthly "
    "living-expense stipend, health insurance in China, and economy-class "
    "round-trip international travel; (3) Postdoctoral Researchers — "
    "receiving a pre-tax stipend of ¥200,000 per year plus economy-class "
    "round-trip international travel; and (4) International PhD Students — "
    "taking regular training courses at the University of Chinese Academy "
    "of Sciences (UCAS) or University of Science and Technology of China "
    "(USTC) for about a year while carrying out research and dissertation "
    "work at a CAS institute. PIFI does not accept direct applications "
    "from foreign scientific research staff: applicants must first "
    "identify an appropriate CAS host researcher at a CAS-affiliated host "
    "institution, who guides the applicant in preparing the application "
    "and submits it on their behalf via CAS's internal Academia Resource "
    "Planning (ARP) system, followed by review at the host institution and "
    "by the PIFI management department of CAS. Applications are accepted "
    "all year round and reviewed in batches, typically within 3 months of "
    "submission — a rolling call rather than a fixed annual deadline. "
    "Further information is available at https://pifi.cas.cn/."
)

SCHEMES: list[dict] = [
    {
        "title":   "CAS President's International Fellowship Initiative (PIFI)",
        "url":     BASE,
        "portal":  PORTAL,
        "deadline": datetime.date(2035, 12, 31),
        "deadline_raw": "Rolling (applications accepted year-round; reviewed in batches, ~3 months)",
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": [
            "Fellowship", "Visiting Scientist Award",
            "Postdoctoral Fellowship", "PhD Fellowship",
        ],
        "individual": [
            "Senior Researcher", "Independent Researcher",
            "Postdoctoral Researcher", "PhD Student",
        ],
        "org_types": ["Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency": "CNY",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "International Relations",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["CN"],
        "desc": DESC,
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
    parser = argparse.ArgumentParser(description="CAS PIFI connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  CAS PIFI — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  CAS PIFI: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
