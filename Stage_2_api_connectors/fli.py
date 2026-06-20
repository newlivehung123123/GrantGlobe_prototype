#!/usr/bin/env python3
"""
Future of Life Institute (FLI) connector.

The Future of Life Institute (FLI) is a non-profit organisation founded in
2014 to steer transformative technology towards benefiting life and away from
extreme large-scale risks. Its primary focus areas are artificial intelligence,
biotechnology, and nuclear weapons. FLI funds external research through
fellowships and competitive grant programmes.

This connector covers four recurring funding programmes:

1. Vitalik Buterin PhD Fellowship in AI Existential Safety
   Five-year fully funded PhD fellowships for students working on technical
   AI existential safety research. Run in partnership with the Beneficial AI
   Foundation (BAIF). Annual deadline: ~21 November.

2. Vitalik Buterin Postdoctoral Fellowship in AI Existential Safety
   Postdoctoral fellowships supporting researchers working on technical AI
   existential safety research at a host institution with a committed mentor.
   Annual deadline: ~5 January.

3. PhD Fellowship in US-China AI Governance Collaboration
   Five-year fully funded PhD fellowships for students researching US-China
   AI governance, including cooperation mechanisms and risk reduction.
   Annual deadline: ~21 November.

4. Digital Media Accelerator
   Rolling-basis funding and support for digital content creators (YouTube,
   TikTok, newsletter/Substack, podcast) producing work on AI safety and
   risk. Explicitly does not require institutional affiliation — eligibility
   rests on an existing following and/or compelling content ideas, not
   academic credentials.

The three fellowship programmes are currently closed for the 2025 cycle.
Deadlines below are the next expected annual opening, based on prior cycle
dates. FLI does not accept unsolicited research grant applications outside
these fellowship and RFP processes, but the Digital Media Accelerator is a
standing rolling call independent of the fellowship cycles.

Source: https://futureoflife.org/our-work/grantmaking-work/
Portal: http://grants.futureoflife.org/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/fli.py [--dry-run]
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

FUNDER  = "Future of Life Institute (FLI)"
DOMAIN  = "api_fli"
BASE    = "https://futureoflife.org/our-work/grantmaking-work/"
PORTAL  = "http://grants.futureoflife.org/"

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. Vitalik Buterin PhD Fellowship in AI Existential Safety ────────
        "title":    "FLI Vitalik Buterin PhD Fellowship in AI Existential Safety",
        "url":      "https://futureoflife.org/grant-program/phd-fellowships/",
        "portal":   PORTAL,
        # Last deadline: 21 November 2025. Next expected: ~21 November 2026.
        "deadline": datetime.date(2026, 11, 21),
        "open_threshold_days": 90,        # applications open ~Sept each year
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Graduate Student"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Artificial Intelligence", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The Vitalik Buterin PhD Fellowship in AI Existential Safety (also known "
            "as the FLI Technical PhD Fellowship) is a fully funded five-year PhD "
            "fellowship for students working on AI existential safety research. It is "
            "run by the Future of Life Institute in partnership with the Beneficial AI "
            "Foundation (BAIF). "
            "Fellows receive tuition and fees for five years of their PhD (with "
            "extension funding possible), a $40,000 annual stipend at universities in "
            "the US, UK, and Canada, a $10,000 annual research fund for travel and "
            "computing, invitations to virtual and in-person research events, and "
            "reimbursement of application fees for up to five PhD programmes for "
            "short-listed applicants. "
            "FLI defines AI existential safety research as research analysing the "
            "most probable pathways to AI-caused existential catastrophe and the "
            "technical work that could minimise such risks. This includes "
            "interpretability and verification of machine learning systems, ensuring "
            "AI systems have objectives that do not incentivise existentially risky "
            "behaviour, and developing formal methods for analysing advanced AI "
            "systems. Applicants must be enrolled in or applying to a PhD programme; "
            "the fellowship is conditional on acceptance to a programme and supervisor "
            "endorsement of the AI existential safety research focus. "
            "There are no geographic restrictions on applicants or host institutions. "
            "The annual application deadline is 21 November. Offers are made by the "
            "end of March the following year. Applications are submitted via "
            "http://grants.futureoflife.org/."
        ),
    },
    {
        # ── 2. Vitalik Buterin Postdoctoral Fellowship ────────────────────────
        "title":    "FLI Vitalik Buterin Postdoctoral Fellowship in AI Existential Safety",
        "url":      "https://futureoflife.org/grant-program/postdoctoral-fellowships/",
        "portal":   PORTAL,
        # Last deadline: 5 January 2026. Next expected: ~5 January 2027.
        "deadline": datetime.date(2027, 1, 5),
        "open_threshold_days": 90,        # applications open ~Oct each year
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Postdoctoral Researcher"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": 80000,
        "amount_max": 80000,
        "currency":   "USD",
        "sectors": [
            "Artificial Intelligence", "Science & Technology",
            "Research & Innovation",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The Vitalik Buterin Postdoctoral Fellowship in AI Existential Safety (also "
            "known as the FLI Technical Postdoctoral Fellowship) supports promising "
            "postdoctoral researchers working on AI existential safety research. It is "
            "run by the Future of Life Institute in partnership with the Beneficial AI "
            "Foundation (BAIF). "
            "Fellows receive an $80,000 annual stipend at universities in the US, UK, "
            "and Canada, and a $10,000 annual research fund for travel and computing. "
            "Applicants must identify and secure commitment from a mentor (typically a "
            "professor) at a host institution (typically a university) before applying; "
            "the mentor must confirm in writing that they will mentor and support the "
            "applicant's AI existential safety research, provide office space, and "
            "integrate the fellow into the local research community. "
            "FLI defines AI existential safety research consistently with its PhD "
            "Fellowship: technical work on interpretability, alignment, verification, "
            "oversight mechanisms, and formal methods for advanced AI systems, to the "
            "extent these directly reduce the risk of existential catastrophe. "
            "There are no geographic restrictions on applicants or host institutions. "
            "The annual application deadline is 5 January. Offers are made by the end "
            "of March. Applications are submitted via http://grants.futureoflife.org/."
        ),
    },
    {
        # ── 3. PhD Fellowship in US-China AI Governance ───────────────────────
        "title":    "FLI PhD Fellowship in US-China AI Governance Collaboration",
        "url":      "https://futureoflife.org/grant-program/us-china-ai-governance-phd-fellowship/",
        "portal":   PORTAL,
        # Last deadline: 21 November 2025. Next expected: ~21 November 2026.
        "deadline": datetime.date(2026, 11, 21),
        "open_threshold_days": 90,
        "cycle_years": 1,
        "grant_types": ["Fellowship"],
        "individual": ["Graduate Student"],
        "org_types":  ["University", "Research Institution"],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Artificial Intelligence", "Science & Technology",
            "Research & Innovation", "International Relations",
            "Policy & Governance",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The FLI PhD Fellowship in US-China AI Governance Collaboration is a "
            "fully funded five-year PhD fellowship for students working on research "
            "that explores risk reduction in US-China relations with respect to AI. "
            "The fellowship was launched in 2024 by the Future of Life Institute. "
            "Fellows receive tuition and fees for five years of their PhD (with "
            "extension funding possible), a $40,000 annual stipend at universities in "
            "the US, UK, and Canada, a $10,000 annual research fund for travel and "
            "computing, invitations to virtual and in-person events, and reimbursement "
            "of application fees for up to five PhD programmes for short-listed "
            "applicants. "
            "Eligible research topics include: investigating political factors shaping "
            "the effectiveness of US-China cooperation on AI governance; exploring "
            "the particular characteristics of AI that make it more or less amenable "
            "to international engagement; analysing the current extent of US-China "
            "collaboration on AI governance; and assessing institutional designs "
            "suitable for US-China AI cooperation, including international norms, "
            "standards, and multilateral institutions. "
            "Applicants must be enrolled in or applying to a PhD programme, with "
            "funding conditional on programme acceptance and supervisor endorsement. "
            "There are no geographic restrictions on applicants or host institutions. "
            "The annual application deadline is 21 November. Applications are "
            "submitted via http://grants.futureoflife.org/."
        ),
    },
    {
        # ── 4. Digital Media Accelerator ──────────────────────────────────────
        "title":    "FLI Digital Media Accelerator",
        "url":      "https://futureoflife.org/project/digital-media-accelerator/",
        "portal":   "https://futureoflife.org/project/digital-media-accelerator/",
        # Rolling programme, no fixed deadline — sentinel-date convention
        # shared with LTFF/EAIF/Emergent Ventures elsewhere in this codebase.
        "deadline": datetime.date(2035, 12, 31),
        "deadline_raw": "Rolling (no fixed deadline)",
        "open_threshold_days": 3500,
        "cycle_years": 5,
        "grant_types": ["Project Grant", "Creator Support"],
        "individual": [
            "Content Creator", "Independent Researcher", "Journalist",
        ],
        "org_types":  [],
        "amount_min": None,
        "amount_max": None,
        "currency":   "USD",
        "sectors": [
            "Artificial Intelligence", "AI Safety",
            "Existential Risk Reduction", "Science Communication",
        ],
        "applicant_countries": [],
        "focus_regions":       ["Global"],
        "focus_countries":     [],
        "desc": (
            "The Digital Media Accelerator is a rolling-basis funding and support "
            "programme for digital content creators producing work on AI safety "
            "and AI risk, run by the Future of Life Institute. Eligible formats "
            "include YouTube channels, TikTok accounts, Substack or other "
            "newsletters, and podcasts. The programme explicitly does not require "
            "institutional affiliation: eligibility is based on an applicant's "
            "existing following and/or the strength of their content ideas about "
            "AI safety, rather than academic or institutional credentials. "
            "Applications are accepted on a rolling basis with no fixed deadline. "
            "Returning applicants may use an Airtable-based Applicant Portal. Due "
            "to the volume of submissions, FLI notes it is not able to give "
            "detailed feedback on every application. Enquiries can be directed to "
            "maggie@futureoflife.org. Apply via "
            "https://futureoflife.org/project/digital-media-accelerator/."
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
    parser = argparse.ArgumentParser(description="Future of Life Institute connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Future of Life Institute — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  FLI: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
