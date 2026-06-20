#!/usr/bin/env python3
"""
JST SATREPS (Japan) connector.

SATREPS (Science and Technology Research Partnership for Sustainable
Development) is a Japanese government program promoting international
joint research between Japan and developing countries on global issues. It
is run jointly by the Japan Science and Technology Agency (JST) — or the
Japan Agency for Medical Research and Development (AMED) for health-related
proposals — and the Japan International Cooperation Agency (JICA).

Of the several JST international-collaboration programs reviewed (JST
top-level funding catalog, ASPIRE, SICORP/CONCERT-Japan), SATREPS is the
only one with a fully verified, currently-published, dated call: the
FY2027 invitation for research proposals. ASPIRE's most recent call has
already closed with no FY2027 call yet announced, and SICORP/CONCERT-Japan
has not yet been independently verified against a clean current deadline,
so both are excluded from this connector pending separate confirmation.

Source: https://www.jst.go.jp/global/english/index.html
        https://www.jst.go.jp/global/english/koubo/selection_process.html

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/jst_satreps.py [--dry-run]
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

FUNDER = "Japan Science and Technology Agency (JST) — SATREPS"
DOMAIN = "api_jst_satreps"
PORTAL_GENERAL = "https://www.jst.go.jp/global/english/koubo/selection_process.html"
ORG_UNI = ["University", "Research Institution", "Government Agency"]

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":    "SATREPS FY2027 Invitation for Research Proposals",
        "url":      "https://www.jst.go.jp/global/english/index.html",
        "portal":   PORTAL_GENERAL,
        # Application period: 18 August – 19 October 2026, 12:00 noon Japan
        # time (tentative, per JST's own published schedule); deadline below
        # is the close of that window.
        "deadline":   datetime.date(2026, 10, 19),
        "cycle_years": 1,
        # The application period itself runs 18 Aug – 19 Oct 2026 (62 days),
        # so the portal opening is sourced directly from JST's own stated
        # window rather than estimated.
        "open_threshold_days": 62,
        "amount_min": None,
        "amount_max": None,
        "sectors":    ["Environment and Energy", "Bioresources",
                       "Disaster Prevention and Mitigation"],
        "individual": ["Researcher", "Senior Researcher"],
        "grant_types": ["Research Grant"],
        "applicant_countries": ["JP"],  # CHAR(2)[] column — ISO-2 code, not full name
        "focus_regions": ["Global", "Developing Countries"],
        "focus_countries": [],
        "desc": (
            "SATREPS (Science and Technology Research Partnership for "
            "Sustainable Development) is a Japanese government program "
            "promoting international joint research between Japan and "
            "developing countries aimed at resolving global issues. It is "
            "structured as a collaboration between JST (or AMED, for "
            "health-related proposals) and the Japan International "
            "Cooperation Agency (JICA). The FY2027 call covers three "
            "research fields — Environment and Energy, Bioresources, and "
            "Disaster Prevention and Mitigation — funding joint research "
            "projects of 3 to 5 years. The (tentative) application period "
            "runs from 18 August to 19 October 2026 at 12:00 noon Japan "
            "time, preceded by a Japanese-language information session on "
            "25 August 2026."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("org_types", ORG_UNI)
    _s.setdefault("currency", "JPY")
    _s.setdefault("applicant_countries", ["JP"])  # CHAR(2)[] column — ISO-2 code, not full name
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
        "application_deadline_raw":  deadline.strftime("%d %B %Y"),
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
    parser = argparse.ArgumentParser(description="JST SATREPS (Japan) connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  JST SATREPS (Japan) — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  JST SATREPS: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
