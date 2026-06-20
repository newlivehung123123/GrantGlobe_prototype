#!/usr/bin/env python3
"""
Survival and Flourishing Fund (SFF) connector.

The Survival and Flourishing Fund (SFF), funded primarily by Jaan Tallinn
and administered by Survival and Flourishing Corp, organizes the "S-Process"
— a recurring grant-round mechanism that has distributed over $150 million
since 2019 to organisations working on the long-term survival and
flourishing of sentient life, with a strong emphasis on AI safety and
governance.

SFF runs an annual S-Process Grant Round consisting of a Main Round (with
three tracks: Main, Freedom, and Fairness) plus, starting in 2026, three
themed Grant Rounds (Climate Change, Animal Welfare, and Human
Self-Enhancement & Empowerment). All tracks share a single rolling
application form, with track- or theme-specific supplemental applications
and deadlines.

This connector represents the 2026 round as six scheme records. Deadlines
auto-advance one year via _advance_deadline once each round closes, since
SFF runs this process annually; exact future dates should be re-verified
against https://survivalandflourishing.fund/ each year as the precise
schedule (themes, deadlines) varies round to round.

Source: https://survivalandflourishing.fund/2026/application
Apply:  https://survivalandflourishing.fund/rolling-application

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/sff.py [--dry-run]
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

FUNDER   = "Survival and Flourishing Fund (SFF)"
DOMAIN   = "api_sff"
BASE     = "https://survivalandflourishing.fund/2026/application"
ROLLING  = "https://survivalandflourishing.fund/rolling-application"

ORG_TYPES = ["Non-Profit Organisation", "For-Profit Company"]
SECTORS_CORE = [
    "Artificial Intelligence", "Existential Risk Reduction",
    "Policy & Governance", "Research & Innovation",
]

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. Main Track ─────────────────────────────────────────────────
        "title":    "SFF S-Process Grant Round — Main Track",
        "url":      BASE,
        "portal":   ROLLING,
        "deadline": datetime.date(2026, 4, 22),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors": SECTORS_CORE,
        "desc": (
            "The Main Track of SFF's annual S-Process Grant Round supports "
            "organisations working on the long-term survival and flourishing "
            "of sentient life, with $10-20MM in funding distributed across "
            "this track. Funded by Jaan Tallinn and administered by Survival "
            "and Flourishing Corp, the S-Process uses a panel of Recommenders "
            "to evaluate applications submitted via a single rolling "
            "application form. Applicants must first receive a Speculation "
            "Grant (over 95% of applicants historically do) to be guaranteed "
            "eligible for consideration. Recommendations are typically "
            "announced several months after the application deadline, with "
            "funding disbursed shortly after. Apply via the SFF Funding "
            "Rolling Application at "
            "https://survivalandflourishing.fund/rolling-application. "
            "Applicants must be a registered charity/non-profit (or be "
            "fiscally sponsored by one) or an incorporated for-profit company "
            "with a company bank account; unsponsored individuals are not "
            "eligible."
        ),
    },
    {
        # ── 2. Freedom Track ─────────────────────────────────────────────────
        "title":    "SFF S-Process Grant Round — Freedom Track",
        "url":      BASE,
        "portal":   ROLLING,
        "deadline": datetime.date(2026, 4, 22),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors": SECTORS_CORE + ["Civil Liberties & Human Rights"],
        "desc": (
            "The Freedom Track is one of three tracks in SFF's annual "
            "S-Process Main Round ($2-4MM budget), evaluated by dedicated "
            "Freedom Track Recommenders. It seeks applications addressing how "
            "AI can be used to avoid concentrations of authority and "
            "strengthen freedom for humans and humanity — including "
            "protection of free speech, privacy, private property, freedom "
            "of association, and the continuation of self-governing, "
            "spatially separated territories. Applicants flag their "
            "interest in this track within the standard SFF Funding Rolling "
            "Application at "
            "https://survivalandflourishing.fund/rolling-application. "
            "Eligibility and process otherwise mirror the Main Track: a "
            "Speculation Grant guarantees consideration, and applicants must "
            "be a registered charity/non-profit (or fiscally sponsored) or "
            "an incorporated for-profit company."
        ),
    },
    {
        # ── 3. Fairness Track ────────────────────────────────────────────────
        "title":    "SFF S-Process Grant Round — Fairness Track",
        "url":      BASE,
        "portal":   ROLLING,
        "deadline": datetime.date(2026, 4, 22),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors": SECTORS_CORE + ["Social Equity & Inclusion"],
        "desc": (
            "The Fairness Track is one of three tracks in SFF's annual "
            "S-Process Main Round ($2-4MM budget), evaluated by dedicated "
            "Fairness Track Recommenders. It seeks applications addressing "
            "how AI can be used to empower the disempowered — including "
            "resisting monopolistic concentration of AI development and "
            "control, defusing conflicts arising from unfair discrimination, "
            "and fostering inclusivity and diversity in AI governance, access, "
            "and benefits. Applicants flag their interest in this track "
            "within the standard SFF Funding Rolling Application at "
            "https://survivalandflourishing.fund/rolling-application. "
            "Eligibility and process otherwise mirror the Main Track: a "
            "Speculation Grant guarantees consideration, and applicants must "
            "be a registered charity/non-profit (or fiscally sponsored) or "
            "an incorporated for-profit company."
        ),
    },
    {
        # ── 4. Climate Change Theme Round ────────────────────────────────────
        "title":    "SFF Theme Round — Climate Change",
        "url":      BASE + "#climate-change",
        "portal":   "https://survivalandflourishing.fund/climate-change-application",
        "deadline": datetime.date(2026, 6, 10),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors": SECTORS_CORE + ["Climate & Environment", "Energy"],
        "desc": (
            "New for 2026, SFF's Climate Change Theme Round funds "
            "organisations working to address the causes and effects of "
            "climate change ($2-4MM budget), including alternative energy, "
            "carbon capture, agricultural innovation, ecosystem restoration, "
            "and policy advocacy, with particular interest in the "
            "intersection of AI and climate. Applicants must submit both the "
            "standard SFF Funding Rolling Application "
            "(https://survivalandflourishing.fund/rolling-application) and "
            "the Climate Change Supplemental Application "
            "(https://survivalandflourishing.fund/climate-change-application). "
            "Late applications are not accepted for this round. Eligible "
            "applicants include registered charities/non-profits (or "
            "fiscally sponsored equivalents) and incorporated for-profit "
            "companies seeking either investment or non-dilutive funding."
        ),
    },
    {
        # ── 5. Animal Welfare Theme Round ────────────────────────────────────
        "title":    "SFF Theme Round — Animal Welfare",
        "url":      BASE + "#animal-welfare",
        "portal":   "https://survivalandflourishing.fund/animal-welfare-application",
        "deadline": datetime.date(2026, 6, 24),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors": SECTORS_CORE + ["Animal Welfare"],
        "desc": (
            "New for 2026, SFF's Animal Welfare Theme Round funds "
            "organisations working to improve animal welfare ($2-4MM "
            "budget), including ethical treatment initiatives, legislative "
            "advocacy, alternative proteins, interspecies communication "
            "research, and agricultural technology, with particular "
            "interest in the intersection of AI and animal welfare. "
            "Applicants must submit both the standard SFF Funding Rolling "
            "Application (https://survivalandflourishing.fund/rolling-application) "
            "and the Animal Welfare Supplemental Application "
            "(https://survivalandflourishing.fund/animal-welfare-application). "
            "Late applications are not accepted for this round. Eligible "
            "applicants include registered charities/non-profits (or "
            "fiscally sponsored equivalents) and incorporated for-profit "
            "companies seeking either investment or non-dilutive funding."
        ),
    },
    {
        # ── 6. Human Self-Enhancement & Empowerment Theme Round ─────────────
        "title":    "SFF Theme Round — Human Self-Enhancement and Empowerment",
        "url":      BASE + "#hsee",
        "portal":   "https://survivalandflourishing.fund/hsee-application",
        "deadline": datetime.date(2026, 7, 8),
        "open_threshold_days": 45,
        "cycle_years": 1,
        "amount_min": None,
        "amount_max": None,
        "sectors": SECTORS_CORE + ["Human Enhancement", "Bioethics"],
        "desc": (
            "New for 2026, SFF's Human Self-Enhancement and Empowerment "
            "(HSEE) Theme Round ($2-4MM budget) funds technical research "
            "advancing human self-enhancement technologies, and philosophical "
            "research on how they should be used, framed as an alternative "
            "path for humans to keep pace with advancing AI. Applicants must "
            "submit both the standard SFF Funding Rolling Application "
            "(https://survivalandflourishing.fund/rolling-application) and "
            "the HSEE Supplemental Application "
            "(https://survivalandflourishing.fund/hsee-application). Late "
            "applications are not accepted for this round. Eligible "
            "applicants include registered charities/non-profits (or "
            "fiscally sponsored equivalents) and incorporated for-profit "
            "companies seeking either investment or non-dilutive funding."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("grant_types", ["Research Grant", "Project Grant"])
    _s.setdefault("individual", [])
    _s.setdefault("org_types", ORG_TYPES)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", ["Global"])
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
        "application_deadline_raw":  f"{deadline.day} {deadline.strftime('%B %Y')} 11:59:59 PM PT",
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
# DB upsert (composite key: source_url + grant_title, since several schemes
# share the same announcement page URL)
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
    parser = argparse.ArgumentParser(description="SFF connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Survival and Flourishing Fund — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  SFF: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
