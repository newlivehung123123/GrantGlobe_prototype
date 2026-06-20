#!/usr/bin/env python3
"""
Academia Sinica (Taiwan) — Postdoctoral Scholar Program connector.

Academia Sinica is Taiwan's national academy and foremost research
institution, spanning the full range of academic disciplines (sciences,
life sciences, humanities, and social sciences). Its Postdoctoral Scholar
Program is genuinely international: eligibility is open to anyone who has
been conferred a PhD on or after a specified cut-off date, with no
nationality restriction stated. Announcements and the application portal
(Academic Service and Management System, ASMS) are published in English.

The programme runs two recruitment rounds per year: a first round
(typically August) and a second round (typically January–March). This
connector models each round as a separate scheme using the annual
cyclical-advance pattern.

Source: https://www.sinica.edu.tw/en/news_content/56/3456
Portal: https://asms.sinica.edu.tw/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/taiwan_academia_sinica.py [--dry-run]
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

FUNDER = "Academia Sinica (Taiwan) — Postdoctoral Scholar Program"
DOMAIN = "api_taiwan_academia_sinica"
BASE   = "https://www.sinica.edu.tw/en/news_content/56/3456"
PORTAL = "https://asms.sinica.edu.tw/"

DESC = (
    "Academia Sinica, Taiwan's national academy and foremost research "
    "institution, runs a Postdoctoral Scholar Program spanning the full "
    "range of academic disciplines — sciences, life sciences, humanities, "
    "and social sciences — across its many constituent institutes. "
    "Eligibility is open to applicants who have been conferred a PhD "
    "degree on or after a specified cut-off date (e.g. on or after 1 "
    "July 2021 for the 2026 cycle), with no nationality restriction "
    "stated. Applications must include a proposal stating research "
    "goals and significance, a literature review, methodology, and "
    "anticipated outcomes. The programme runs two recruitment rounds "
    "per year — a first round (typically opening around 1 August) and "
    "a second round (typically opening around 15 January) — each with "
    "an online submission deadline roughly one month later. Successful "
    "applicants are appointed for a fixed term beginning the following "
    "July. Applications are submitted online via Academia Sinica's "
    "Academic Service and Management System (ASMS) at "
    "https://asms.sinica.edu.tw/, and round announcements are published "
    "in English at https://www.sinica.edu.tw/en/."
)

SCHEMES: list[dict] = [
    {
        "title":   "Academia Sinica Postdoctoral Scholar Program — Round 1",
        "url":     BASE,
        "portal":  PORTAL,
        # Round 1: online applications typically close around 1 September.
        "deadline": datetime.date(2026, 9, 1),
        "open_threshold_days": 31,        # submission window opens ~1 August
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  [],
        "amount_min": None,
        "amount_max": None,
        "currency":   "TWD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["TW"],
        "desc": DESC,
    },
    {
        "title":   "Academia Sinica Postdoctoral Scholar Program — Round 2",
        "url":     BASE,
        "portal":  PORTAL,
        # Round 2: online applications typically close around 2-3 March.
        "deadline": datetime.date(2026, 3, 2),
        "open_threshold_days": 46,        # submission window opens ~15 January
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  [],
        "amount_min": None,
        "amount_max": None,
        "currency":   "TWD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["TW"],
        "desc": DESC,
    },
    {
        # ── 3. IHP Fellowships for Doctoral Candidates ────────────────────────
        "title":   "Academia Sinica IHP Fellowships for Doctoral Candidates in the Humanities and Social Sciences",
        "url":     "https://www1.ihp.sinica.edu.tw/en/Bulletin/News/2612/Detail",
        "portal":  "https://www1.ihp.sinica.edu.tw/en/OutReach/Scholarship",
        # 2026 cycle: application period ends 24 February 2026 (postmark
        # deadline, already closed at authoring time).
        "deadline": datetime.date(2026, 2, 24),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Doctoral Fellowship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": None,
        "amount_max": None,
        "currency": "TWD",
        "sectors": [
            "Humanities", "Social Sciences",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["TW"],
        "desc": (
            "The Institute of History and Philology (IHP) at Academia "
            "Sinica offers fellowships for doctoral candidates to write "
            "their dissertations in residence at IHP, in the fields of "
            "history, archaeology, anthropology, and philology. "
            "Applicants must be full-time graduate students (not "
            "employed) who have completed coursework and been awarded "
            "doctoral-candidate status at a humanities or social "
            "sciences department in Taiwan or abroad, and must plan to "
            "write their dissertation while at IHP. Citizens of mainland "
            "China cannot apply, per Taiwanese law, but the fellowship is "
            "otherwise open to graduate students worldwide. Each "
            "successful applicant receives NT$50,000 per month for a "
            "fellowship period of one year (renewable to a maximum of "
            "two years), running 1 July to 30 June, conditional on not "
            "concurrently holding other long-term scholarships. Fellows "
            "must conduct research at IHP for at least half the funding "
            "period and submit progress reports every six months. "
            "Applications (including a research plan of up to 5 pages, "
            "which may be written in Chinese or English, plus "
            "supporting documents and two recommendation letters) are "
            "sent by post and email to the IHP Secretariat. The 2026 "
            "cycle's application period ended 24 February 2026 "
            "(postmark deadline); subsequent cycles follow a similar "
            "annual schedule."
        ),
    },
    {
        # ── 4. Taiwan International Graduate Program (TIGP) ───────────────────
        "title":   "Taiwan International Graduate Program (TIGP) PhD Programs",
        "url":     "https://tigp.sinica.edu.tw/pages/3096",
        "portal":  "https://tigp.sinica.edu.tw/pages/2757",
        # Application deadline for Fall-semester admission: 1 February
        # each year (already closed at authoring time).
        "deadline": datetime.date(2026, 2, 1),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["PhD Scholarship"],
        "individual": ["PhD Student"],
        "org_types": [],
        "amount_min": 40000,
        "amount_max": 40000,
        "currency": "TWD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions": [],
        "focus_countries": ["TW"],
        "desc": (
            "The Taiwan International Graduate Program (TIGP) is "
            "Academia Sinica's English-medium PhD programme, jointly run "
            "with partner universities, spanning 13 programmes conducted "
            "entirely in English plus one humanities programme with some "
            "courses taught in Chinese. TIGP is genuinely international: "
            "applicants of any nationality may apply for admission to "
            "the Fall semester intake. Admitted students receive a "
            "tax-free stipend of NT$40,000 per month in the first year "
            "(extended for a second year for students who perform well), "
            "with tuition fees subsidised for up to five consecutive "
            "years (during which students pay the same tuition as local "
            "students); additional fellowships (Presidential Fellowship, "
            "Research Performance Fellowship, Rising Star Fellowship, "
            "Travel Grants) are available to current students on top of "
            "the base stipend. The annual application deadline for "
            "Fall-semester admission is 1 February; subsequent cycles "
            "follow a similar annual schedule. Applications are "
            "submitted via TIGP's online application system at "
            "https://tigp.sinica.edu.tw/pages/2757."
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
    parser = argparse.ArgumentParser(description="Academia Sinica connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Academia Sinica — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Academia Sinica: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
