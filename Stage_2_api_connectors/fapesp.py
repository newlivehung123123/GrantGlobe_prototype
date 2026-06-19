#!/usr/bin/env python3
"""
São Paulo Research Foundation (FAPESP, Brazil) connector.

FAPESP is one of Brazil's principal state research-funding agencies,
supporting researchers and institutions based in the state of São Paulo
across all fields of knowledge. Most of FAPESP's international funding is
channelled through bilateral and multilateral "Calls for Proposals" run
jointly with partner agencies abroad (ERC, DFG, NSF, BBSRC, NRF Korea,
Confap/Horizon Europe, etc.), some with fixed annual deadlines and some
accepted on a continuous, rolling basis with no fixed deadline.

This connector represents seven such international-collaboration
mechanisms, drawn directly from FAPESP's own "Calls for Proposals" page.
Rolling/continuous-flow mechanisms use a far-future sentinel deadline (the
same convention used elsewhere in this pipeline for rolling-admission
programs, e.g. the Long-Term Future Fund) so that they always display as
"Open," consistent with FAPESP's own "Proposals may be submitted at any
time" language for those mechanisms.

Note: an earlier scouting pass on this funder concluded "unbuildable" based
on an unrelated/stale URL; the canonical https://fapesp.br/calls page
returns full, well-structured, server-rendered HTML and is reliably
scrapable, reversing that earlier conclusion.

Source: https://fapesp.br/calls

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/fapesp.py [--dry-run]
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

FUNDER = "São Paulo Research Foundation (FAPESP)"
DOMAIN = "api_fapesp"
PORTAL_GENERAL = "https://fapesp.br/en"
ORG_UNI = ["University", "Research Institution"]

# Far-future sentinel for rolling/continuous-flow mechanisms with no fixed
# deadline, so the scheme always evaluates to "Open" — same convention used
# for the Long-Term Future Fund (ltff.py) elsewhere in this pipeline.
ROLLING_SENTINEL = datetime.date(2035, 12, 31)

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        # ── 1. FAPESP – Confap – ERC 2026 Call ──────────────────────────────
        "title":    "FAPESP – Confap – European Research Council (ERC) Call",
        "url":      "https://fapesp.br/18159",
        "portal":   PORTAL_GENERAL,
        "deadline":   datetime.date(2026, 7, 10),
        "cycle_years": 1,
        "open_threshold_days": 45,
        "amount_min": None,
        "amount_max": None,
        "sectors":    [],
        "individual": ["Researcher"],
        "grant_types": ["Fellowship"],
        "focus_countries": ["Brazil", "European Union"],
        "desc": (
            "Annual call run jointly by FAPESP, the National Council of "
            "State Funding Agencies (Confap), and the European Research "
            "Council, supporting collaborations between researchers based "
            "in the state of São Paulo and European scientists holding or "
            "applying for an ERC grant, via FAPESP's Research Fellowship "
            "Abroad (BPE) mechanism. Open to all areas of knowledge."
        ),
    },
    {
        # ── 2. PROPASP (Germany) ────────────────────────────────────────────
        "title":    "PROPASP (Programa de Pesquisa Alemanha – São Paulo)",
        "url":      "https://fapesp.br/18123",
        "portal":   PORTAL_GENERAL,
        "deadline":   datetime.date(2026, 6, 8),
        "cycle_years": 1,
        "open_threshold_days": 45,
        "amount_min": None,
        "amount_max": None,
        "sectors":    [],
        "individual": ["Researcher"],
        "grant_types": ["Mobility Grant"],
        "focus_countries": ["Brazil", "Germany"],
        "desc": (
            "Annual call allowing researchers who already hold an ongoing "
            "FAPESP grant to apply for academic exchange and mobility "
            "funding to collaborate with German research projects, in any "
            "area of knowledge."
        ),
    },
    {
        # ── 3. FAPESP – National Research Foundation of Korea ──────────────
        "title":    "FAPESP – National Research Foundation of Korea",
        "url":      "https://fapesp.br/18200",
        "portal":   PORTAL_GENERAL,
        "deadline":   datetime.date(2026, 6, 30),
        "cycle_years": 1,
        "open_threshold_days": 45,
        "amount_min": None,
        "amount_max": None,
        "sectors":    [],
        "individual": ["Researcher"],
        "grant_types": ["Research Grant"],
        "focus_countries": ["Brazil", "South Korea"],
        "desc": (
            "Joint call between FAPESP and South Korea's National Research "
            "Foundation (NRF) supporting collaborative Regular Research "
            "Grant projects between researchers based in the state of São "
            "Paulo and counterparts in South Korea, open to all areas of "
            "knowledge."
        ),
    },
    {
        # ── 4. FAPESP/Confap/Horizon Europe (rolling) ───────────────────────
        "title":    "FAPESP/Confap/Horizon Europe",
        "url":      "https://fapesp.br/16466",
        "portal":   PORTAL_GENERAL,
        "deadline":   ROLLING_SENTINEL,
        "cycle_years": 5,
        "open_threshold_days": 3500,
        "amount_min": None,
        "amount_max": None,
        "sectors":    [],
        "individual": ["Researcher"],
        "grant_types": ["Research Grant"],
        "focus_countries": ["Brazil", "European Union"],
        "desc": (
            "Standing mechanism, run with Confap, enabling researchers "
            "based in the state of São Paulo to participate in Horizon "
            "Europe consortia, with FAPESP co-funding the São Paulo "
            "partners' share of the work through its Regular Research "
            "Grant, Thematic Grant, or Young Investigator Award "
            "mechanisms. Proposals may be submitted at any time, in any "
            "area of knowledge."
        ),
    },
    {
        # ── 5. DFG (Germany, rolling) ───────────────────────────────────────
        "title":    "FAPESP – Deutsche Forschungsgemeinschaft (DFG)",
        "url":      "https://fapesp.br/5398/dfg",
        "portal":   PORTAL_GENERAL,
        "deadline":   ROLLING_SENTINEL,
        "cycle_years": 5,
        "open_threshold_days": 3500,
        "amount_min": None,
        "amount_max": None,
        "sectors":    [],
        "individual": ["Researcher"],
        "grant_types": ["Research Grant"],
        "focus_countries": ["Brazil", "Germany"],
        "desc": (
            "Standing cooperation agreement between FAPESP and Germany's "
            "DFG, matching FAPESP's Regular Research Grant and Thematic "
            "Grant mechanisms with DFG's Individual Research Grants and "
            "Coordinated Programmes for joint Brazil-Germany research "
            "projects, in any area of knowledge. Proposals may be "
            "submitted at any time."
        ),
    },
    {
        # ── 6. NSF Directorate for Geosciences (rolling) ────────────────────
        "title":    "FAPESP – National Science Foundation, Directorate for Geosciences",
        "url":      "https://fapesp.br/17293",
        "portal":   PORTAL_GENERAL,
        "deadline":   ROLLING_SENTINEL,
        "cycle_years": 5,
        "open_threshold_days": 3500,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Geosciences"],
        "individual": ["Researcher"],
        "grant_types": ["Research Grant"],
        "focus_countries": ["Brazil", "United States"],
        "desc": (
            "Standing cooperation between FAPESP and the U.S. National "
            "Science Foundation's Directorate for Geosciences, supporting "
            "joint Brazil-US geosciences research through FAPESP's Regular "
            "Research Grant and Thematic Grant mechanisms. Proposals are "
            "accepted year-round."
        ),
    },
    {
        # ── 7. FAPESP-BBSRC Pump-Priming Award (rolling) ────────────────────
        "title":    "FAPESP-BBSRC Pump-Priming Award (FAPPA)",
        "url":      "https://fapesp.br/11999",
        "portal":   PORTAL_GENERAL,
        "deadline":   ROLLING_SENTINEL,
        "cycle_years": 5,
        "open_threshold_days": 3500,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Biological Sciences", "Biotechnology"],
        "individual": ["Researcher"],
        "grant_types": ["Research Grant"],
        "focus_countries": ["Brazil", "United Kingdom"],
        "desc": (
            "Standing cooperation between FAPESP and the UK's Biotechnology "
            "and Biological Sciences Research Council (BBSRC), funding "
            "pump-priming projects in the biological sciences and "
            "biotechnology, with priority given to food safety, bioenergy, "
            "and industrial biotechnology topics. Proposals may be "
            "submitted at any time, via FAPESP's Regular Research Grant "
            "(APR) mechanism."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_UNI)
    _s.setdefault("currency", "BRL")
    _s.setdefault("applicant_countries", ["Brazil"])
    _s.setdefault("focus_regions", ["Brazil"])
    _s.setdefault("focus_countries", ["Brazil"])


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
    is_rolling = scheme["deadline"] == ROLLING_SENTINEL

    if days_until < 0:
        status = "Closed"
    elif days_until <= thr:
        status = "Open"
    else:
        status = "Forthcoming"

    opening = deadline - datetime.timedelta(days=thr)
    deadline_iso = deadline.isoformat()
    deadline_raw = "Rolling (no fixed deadline)" if is_rolling else deadline.strftime("%d %B %Y")

    return {
        "grant_title":               scheme["title"],
        "funder_name":               FUNDER,
        "source_url":                scheme["url"],
        "application_portal_url":    scheme["portal"],
        "description":               scheme["desc"],
        "application_deadline":      deadline_iso,
        "application_deadline_raw":  deadline_raw,
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
    parser = argparse.ArgumentParser(description="FAPESP (Brazil) connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  FAPESP (Brazil) — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  FAPESP: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
