#!/usr/bin/env python3
"""
National Natural Science Foundation of China (NSFC) connector.

The Research Fund for International Scientists (RFIS) is set up by the
National Natural Science Foundation of China (NSFC) to support international
scientists of foreign citizenship who are ready to conduct basic research and
applied basic research at host institutions in China's mainland. RFIS is
documented and submitted in English (Title/Abstract/Keywords are required in
both English and Chinese), satisfying this project's English-language
standing constraint, and is one of the few NSFC programmes open to applicants
without Chinese institutional affiliation prior to application.

RFIS consists of three sub-types, all sharing the same annual submission
window: RFIS-I (International Young Scientists), RFIS-II (International
Excellent Young Scientists), and RFIS-III (International Senior Scientists).
Eligibility requires the applicant to take up a position at a China-mainland
host institution registered with NSFC (an Agreement to Support the
Application is signed with the host institution), so this scheme is
institutional/host-affiliated rather than open to fully independent
applicants — consistent with the project's general national-funder
connectors (NSF, NIH, ERC, etc.).

Deadline pattern — annual cycle. The 2026 call (guidelines published 20 Jan
2026) had a submission window of 1–20 March 2026, which has already closed
as of this connector's authoring date. The next cycle is expected to open on
a similar annual schedule (~January call guidelines, ~March submission
window), so the deadline below is advanced by one year via the same
cyclical-advance helper used elsewhere in this codebase (e.g. hhmi.py) until
it falls in the future.

Source: https://www.nsfc.gov.cn/english/site_1/international/D5/index.html
Portal: https://grants.nsfc.gov.cn/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/china_nsfc.py [--dry-run]
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

FUNDER = "National Natural Science Foundation of China (NSFC)"
DOMAIN = "api_china_nsfc"
BASE   = "https://www.nsfc.gov.cn/english/site_1/international/D5/index.html"
PORTAL = "https://grants.nsfc.gov.cn/"

DESC = (
    "The Research Fund for International Scientists (RFIS) is set up by the "
    "National Natural Science Foundation of China (NSFC) to support "
    "international scientists of foreign citizenship who are ready to "
    "conduct basic research and applied basic research at host institutions "
    "in China's mainland, and to enhance long-term, sustainable academic "
    "collaboration between Chinese and international scientists. RFIS "
    "consists of three sub-types sharing the same annual submission window: "
    "RFIS-I (International Young Scientists, doctoral degree obtained within "
    "the past 6 years), RFIS-II (International Excellent Young Scientists, "
    "doctoral degree within the past 15 years and a senior academic title of "
    "Associate Professor or higher), and RFIS-III (International Senior "
    "Scientists, senior academic title with outstanding academic achievements "
    "and significant international influence). Funding areas span all NSFC "
    "disciplines: Mathematical and Physical Sciences, Chemical Sciences, Life "
    "Sciences, Earth Sciences, Engineering and Material Sciences, Information "
    "Sciences, Management Sciences, Health Sciences, and Interdisciplinary "
    "Sciences. Applicants commit to working no less than 9 months per "
    "calendar year at the host institution during the project, and an "
    "Agreement to Support the Application must be signed between the "
    "applicant and the China-mainland host institution (which must be "
    "registered with NSFC). Direct cost is 200,000 RMB/year for RFIS-I, "
    "400,000 RMB/year for RFIS-II, and 800,000 RMB/year for RFIS-III, for a "
    "one- or two-year project. The application form must be prepared in "
    "English (Title, Abstract, and Keywords are also required in Chinese). "
    "The 2026 cycle's submission window ran from 1 to 20 March 2026 "
    "(16:00 Beijing time), following call guidelines published 20 January "
    "2026; the next cycle is expected to follow a similar annual schedule. "
    "Submission is via NSFC's Internet-based Science Information System at "
    "https://grants.nsfc.gov.cn/."
)

SCHEMES: list[dict] = [
    {
        "title":    "NSFC Research Fund for International Scientists (RFIS)",
        "url":      BASE,
        "portal":   PORTAL,
        # 2026 cycle deadline: 20 March 2026 (already closed). Advances by
        # one year via _advance_deadline until in the future.
        "deadline": datetime.date(2026, 3, 20),
        "open_threshold_days": 60,        # call guidelines published ~20 Jan
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": [
            "Postdoctoral Researcher", "Early Career Researcher",
            "Senior Researcher",
        ],
        "org_types":  ["University", "Research Institution"],
        "amount_min": 200000,
        "amount_max": 800000,
        "currency":   "CNY",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "International Relations",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["CN"],
        "desc": DESC,
    },
    {
        # ── 2. International Collaboration Fund for Creative Research Teams ──
        "title":    "NSFC International Collaboration Fund for Creative Research Teams (ICFCRT)",
        "url":      "https://www.nsfc.gov.cn/english/site_1/international/D6/index.html",
        "portal":   PORTAL,
        # 2026 cycle deadline: 20 March 2026 (already closed). Advances by
        # one year via _advance_deadline until in the future.
        "deadline": datetime.date(2026, 3, 20),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": 4800000,
        "amount_max": 7200000,
        "currency":   "CNY",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "International Relations",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["CN"],
        "desc": (
            "The International Collaboration Fund for Creative Research "
            "Teams (ICFCRT) is set up by the National Natural Science "
            "Foundation of China (NSFC) to enhance international "
            "scientific collaboration by supporting pioneering "
            "scientists of foreign citizenship in building and leading "
            "research teams at a China-mainland host institution, "
            "carrying out creative basic and applied basic research on "
            "self-selected topics within NSFC's funding scope. The "
            "Principal Investigator must hold foreign citizenship and a "
            "senior academic title, have outstanding academic "
            "achievements and significant international influence, and "
            "commit to working no less than 6 months per calendar year "
            "at the host institution; an Agreement to Support the "
            "Application must be signed between the applicant and the "
            "host institution. Each project may include up to 4 "
            "backbone researchers (of any nationality, holding senior "
            "academic titles or doctoral degrees) across up to 2 "
            "participating institutions. Projects run for three years "
            "(the 2026 cycle covers January 2027-December 2029) with a "
            "total direct cost of 6 million RMB per project (4.8 million "
            "RMB for Mathematical Sciences and Management Sciences "
            "projects) plus 1.2 million RMB indirect cost. The "
            "application must be prepared in English (Title, Abstract, "
            "and Keywords also in Chinese). The 2026 cycle's submission "
            "window ran from 1 to 20 March 2026 (16:00 Beijing time); the "
            "next cycle is expected to follow a similar annual schedule. "
            "Submission is via NSFC's Internet-based Science Information "
            "System at https://grants.nsfc.gov.cn/."
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
        "application_deadline_raw":  f"{deadline.day} {deadline.strftime('%B %Y')} (Beijing time)",
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
    parser = argparse.ArgumentParser(description="NSFC connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  NSFC — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  NSFC: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
