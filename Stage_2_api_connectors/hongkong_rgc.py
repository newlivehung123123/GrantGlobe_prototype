#!/usr/bin/env python3
"""
Research Grants Council (RGC), Hong Kong connector.

Hong Kong is part of China with English as one of its two official
languages, and the Research Grants Council (RGC) — the territory's
flagship academic-research funder, overseen by the University Grants
Committee (UGC) — publishes its call letters, guidance notes, and
electronic application system (CERG1) entirely in English. This connector
covers the General Research Fund (GRF) and Early Career Scheme (ECS), RGC's
largest and most widely used schemes, run as a single combined annual
exercise.

The 2026/27 exercise's external (UGC Secretariat) deadline was 31 October
2025, with the RGC Electronic System open for submission from 22 August
2025. Eligibility requires the Principal Investigator to hold a position of
Assistant Professor or above (or career-equivalent) at a UGC-funded Hong
Kong institution; the ECS variant is for academics within their first three
years of a substantiation/tenure-track appointment. All academic
disciplines are eligible.

Deadline pattern — annual cycle (cyclical-advance, as in hhmi.py/fli.py).

Source: https://www.ugc.edu.hk/eng/rgc/funding_opport/share/grfecs_call_letter.html
Portal: http://cerg1.ugc.edu.hk/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/hongkong_rgc.py [--dry-run]
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

FUNDER = "Research Grants Council (RGC), Hong Kong"
DOMAIN = "api_hongkong_rgc"
BASE   = "https://www.ugc.edu.hk/eng/rgc/funding_opport/share/grfecs_call_letter.html"
PORTAL = "http://cerg1.ugc.edu.hk/"

SCHEMES: list[dict] = [
    {
        "title":    "RGC General Research Fund (GRF) / Early Career Scheme (ECS)",
        "url":      BASE,
        "portal":   PORTAL,
        # 2026/27 exercise external deadline: 31 October 2025 (already
        # closed at authoring time). Advances annually to the next exercise.
        "deadline": datetime.date(2025, 10, 31),
        "open_threshold_days": 75,        # electronic system opens ~22 Aug
        "cycle_years": 1,
        "grant_types": ["Research Grant", "Early Career Grant"],
        "individual": [
            "Assistant Professor", "Early Career Researcher",
            "Senior Researcher",
        ],
        "org_types":  ["University"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "HKD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Social Sciences", "Humanities",
        ],
        "applicant_countries": ["Hong Kong"],
        "focus_regions":       [],
        "focus_countries":     ["Hong Kong"],
        "desc": (
            "The General Research Fund (GRF) and Early Career Scheme (ECS) "
            "are run by Hong Kong's Research Grants Council (RGC), under "
            "the University Grants Committee (UGC), as a combined annual "
            "funding exercise covering all academic disciplines. The GRF "
            "supports individual or team research projects of "
            "demonstrated merit; the ECS supports academics within the "
            "first three years of a substantiation-track or tenure-track "
            "Assistant Professor (or career-equivalent) appointment, who "
            "may apply under the GRF or the ECS but not both in the same "
            "cycle. The Principal Investigator must hold an appointment "
            "of Assistant Professor level or above (or career-equivalent) "
            "at a UGC-funded Hong Kong institution. Applications are "
            "submitted entirely in English through the RGC's CERG1 "
            "electronic system. The 2026/27 exercise's external (UGC "
            "Secretariat) deadline was 31 October 2025, with the "
            "electronic system open for submission from 22 August 2025; "
            "subsequent exercises follow a similar annual schedule. Full "
            "guidance is published in the Scheme Overview and Guidance "
            "Notes (GRF2/ECS2) on the RGC's official call-letter page."
        ),
    },
    {
        # ── 2. Hong Kong PhD Fellowship Scheme (HKPFS) ────────────────────────
        "title":    "Hong Kong PhD Fellowship Scheme (HKPFS)",
        "url":      "https://cerg1.ugc.edu.hk/hkpfs/apply.html",
        "portal":   "https://cerg1.ugc.edu.hk/hkpfs/apply.html",
        # 2026/27 exercise deadline: 1 December 2025, 12:00 noon (already
        # closed at authoring time). Advances annually to the next exercise.
        "deadline": datetime.date(2025, 12, 1),
        "open_threshold_days": 95,        # applications open ~September each year
        "cycle_years": 1,
        "grant_types": ["PhD Scholarship"],
        "individual": ["PhD Student"],
        "org_types":  ["University"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "HKD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["Hong Kong"],
        "desc": (
            "The Hong Kong PhD Fellowship Scheme (HKPFS), run by the "
            "Research Grants Council (RGC), is a prestigious, fully "
            "funded scheme for outstanding students worldwide aiming to "
            "pursue full-time PhD studies at any of Hong Kong's eight "
            "UGC-funded universities. The scheme is open to applicants "
            "of any nationality or ethnic background. Applicants apply "
            "both to the HKPFS and, separately, for PhD admission at "
            "their chosen Hong Kong institution; selection is run "
            "centrally by the RGC across all participating universities. "
            "The 2026/27 exercise's deadline was 1 December 2025, 12:00 "
            "noon (Hong Kong time), with successful candidates notified "
            "by RGC in May 2026; subsequent exercises follow a similar "
            "annual schedule. Full details and the application form are "
            "available at https://cerg1.ugc.edu.hk/hkpfs/apply.html."
        ),
    },
    {
        # ── 3. Junior Research Fellow Scheme (JRFS) ───────────────────────────
        "title":    "RGC Junior Research Fellow Scheme (JRFS)",
        "url":      "https://www.ugc.edu.hk/eng/rgc/funding_opport/jrfs",
        "portal":   "https://www.ugc.edu.hk/eng/rgc/funding_opport/jrfs/how_to_apply.html",
        # JRFS (2026/27 cohort) nomination deadline: 31 October 2025
        # (already closed at authoring time). Advances annually.
        "deadline": datetime.date(2025, 10, 31),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Postdoctoral Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  ["University"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "HKD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Social Sciences", "Humanities",
        ],
        "applicant_countries": [],
        "focus_regions":       [],
        "focus_countries":     ["Hong Kong"],
        "desc": (
            "The RGC Junior Research Fellow Scheme (JRFS, formerly known "
            "as the RGC Postdoctoral Fellowship Scheme, renamed effective "
            "the 2025/26 selection exercise) provides 60 awardees per "
            "yearly exercise with 24 months of full-time postdoctoral "
            "research support at a UGC-funded Hong Kong university, with "
            "an optional 12-month extension, and a pathway to transition "
            "into Assistant Professor or Research Assistant Professor "
            "positions during the fellowship. Each university may "
            "nominate up to 15 candidates (nominees must hold the legal "
            "right to work and reside in Hong Kong, and must have been "
            "conferred a PhD no more than three years before the "
            "exercise, or be due to complete one shortly). JRFS spans "
            "all academic disciplines across two streams: Humanities, "
            "Social Sciences and Business Studies; and Sciences, "
            "Medicine, Engineering and Technology. Nominations are "
            "submitted by universities, not directly by candidates. The "
            "nomination deadline for the JRFS (2026/27) was 31 October "
            "2025, 5:00pm; subsequent exercises follow a similar annual "
            "schedule."
        ),
    },
    {
        # ── 4. Collaborative Research Fund (CRF) ──────────────────────────────
        "title":    "RGC Collaborative Research Fund (CRF)",
        "url":      "https://www.ugc.edu.hk/eng/rgc/funding_opport/crf/call_letter.html",
        "portal":   "https://www.ugc.edu.hk/eng/rgc/funding_opport/crf/how_to_apply.html",
        # CRF 2026/27 exercise: preliminary proposals due 23 Feb 2026
        # (electronic) / 27 Feb 2026 (hard copy, already closed).
        "deadline": datetime.date(2026, 2, 27),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher"],
        "org_types":  ["University"],
        "amount_min": 2000000,
        "amount_max": 10000000,
        "currency":   "HKD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Social Sciences", "Humanities",
        ],
        "applicant_countries": ["Hong Kong"],
        "focus_regions":       [],
        "focus_countries":     ["Hong Kong"],
        "desc": (
            "The RGC Collaborative Research Fund (CRF) supports "
            "multi-investigator, multi-disciplinary projects across "
            "Hong Kong's UGC-funded universities, encouraging research "
            "groups to engage in collaborative research across "
            "disciplines and institutions. CRF offers three grant "
            "types: the Collaborative Research Project Grant (CRPG, "
            "HK$2-10 million per project), the Collaborative Research "
            "Equipment Grant (CREG, HK$2-10 million per project, for "
            "major shared research facilities/equipment), and the Young "
            "Collaborative Research Grant (YCRG, HK$2-5 million per "
            "project, regularised since 2025/26 to support young "
            "researchers leading collaborative projects). CRF projects "
            "normally run up to three years (four to five years in "
            "exceptional cases). Applications undergo a two-stage "
            "assessment process. Preliminary proposals for the 2026/27 "
            "exercise were due 23 February 2026 (electronic) / 27 "
            "February 2026 (hard copy); subsequent exercises follow a "
            "similar annual schedule."
        ),
    },
    {
        # ── 5. Research Impact Fund (RIF) ─────────────────────────────────────
        "title":    "RGC Research Impact Fund (RIF)",
        "url":      "https://www.ugc.edu.hk/eng/rgc/funding_opport/rif/call_letter.html",
        "portal":   "https://www.ugc.edu.hk/eng/rgc/funding_opport/rif/how_to_apply.html",
        # RIF 2026/27 exercise: preliminary proposals due 27 Feb 2026
        # (electronic) / 4 March 2026 (hard copy, already closed).
        "deadline": datetime.date(2026, 3, 4),
        "open_threshold_days": 75,
        "cycle_years": 1,
        "grant_types": ["Research Grant"],
        "individual": ["Senior Researcher"],
        "org_types":  ["University"],
        "amount_min": 3000000,
        "amount_max": 10000000,
        "currency":   "HKD",
        "sectors": [
            "Science & Technology", "Research & Innovation",
            "Social Sciences", "Humanities", "Innovation Policy",
        ],
        "applicant_countries": ["Hong Kong"],
        "focus_regions":       [],
        "focus_countries":     ["Hong Kong"],
        "desc": (
            "The RGC Research Impact Fund (RIF) encourages Hong Kong "
            "academics to pursue impactful and translational research "
            "projects that deliver benefit for the wider community, and "
            "to engage in collaborative research beyond academia (e.g. "
            "with government departments, the business sector, industry, "
            "or other research institutes). Proposals are assessed on "
            "academic merit and potential research impact. The RGC "
            "reserved HK$75 million for the 2026/27 exercise, requiring "
            "mandatory matching funds on a 70% (RGC) / 30% "
            "(university/partner) basis; net RGC funding requested per "
            "project ranges from HK$3-10 million over a three- to "
            "five-year project duration. Preliminary proposals for the "
            "2026/27 exercise were due 27 February 2026 (electronic) / 4 "
            "March 2026 (hard copy); subsequent exercises follow a "
            "similar annual schedule."
        ),
    },
    {
        # ── 6. Humanities and Social Sciences Prestigious Fellowship ─────────
        "title":    "RGC Humanities and Social Sciences Prestigious Fellowship Scheme (HSSPFS)",
        "url":      "https://www.ugc.edu.hk/eng/rgc/funding_opport/hsspfs/",
        "portal":   "https://www.ugc.edu.hk/eng/rgc/funding_opport/hsspfs/how_to_apply.html",
        # HSSPFS 2026/27 exercise deadline: 4 February 2026 (already closed).
        "deadline": datetime.date(2026, 2, 4),
        "open_threshold_days": 60,
        "cycle_years": 1,
        "grant_types": ["Research Fellowship"],
        "individual": ["Senior Researcher"],
        "org_types":  ["University"],
        "amount_min": None,
        "amount_max": 1000000,
        "currency":   "HKD",
        "sectors": ["Humanities", "Social Sciences"],
        "applicant_countries": ["Hong Kong"],
        "focus_regions":       [],
        "focus_countries":     ["Hong Kong"],
        "desc": (
            "Introduced in 2012/13, the Humanities and Social Sciences "
            "Prestigious Fellowship Scheme (HSSPFS) grants extended "
            "time-off and supporting funds (up to HK$1 million per "
            "award) to outstanding investigators in the Humanities and "
            "Social Sciences Panel disciplines, enabling them to focus "
            "on research and writing for up to 12 months, with relief "
            "from teaching and administrative duties and funding for "
            "relief-teacher salary costs and research project costs "
            "(staff, equipment, travel, subsistence, dissemination). "
            "All eight UGC-funded universities may each nominate up to "
            "five candidates; eligible applicants must be full-time "
            "academic staff at Staff Grades 'A' to 'I', spending at "
            "least 80% of their time on degree-level work, with salary "
            "wholly funded by the university. Visiting scholars are not "
            "eligible, and past HSSPFS awardees cannot compete again. "
            "Applications for the 2026/27 exercise were due 4 February "
            "2026; subsequent exercises follow a similar annual "
            "schedule."
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
    parser = argparse.ArgumentParser(description="RGC Hong Kong connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  RGC Hong Kong — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  RGC Hong Kong: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
