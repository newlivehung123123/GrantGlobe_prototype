#!/usr/bin/env python3
"""
Pacific Forum (Honolulu, US) — Legacy Fellowships connector.

Pacific Forum is an Indo-Pacific-focused foreign-policy think tank running
several fellowship programs for early/mid-career researchers and
practitioners. Its three "Legacy Fellowships" — the Lloyd and Lilian Vasey
Fellowship, the James A. Kelly Korea Fellowship, and the WSD-Handa
Fellowship — share two fixed annual application deadlines, stated directly
on the fellowships listing page: April 30 (for fellows starting in the
fall/winter cohort) and October 31 (for fellows starting in the
spring/summer cohort). Each Legacy Fellowship offers both a resident
(six-month) and a non-resident (one-year) track.

Three further "Partner-sponsored" fellowships (Women, Peace, and Security;
Korea Foundation; Nonproliferation) and several "Technology Policy"
fellowships (India, Vietnam, Philippines, Japan-US/JUST) also exist on the
same site but are excluded from this connector pending separate
verification of their individual deadlines.

The application-window length (i.e., how long before each deadline the
portal opens) is not separately published, so open_threshold_days below is
a conservative estimate, not a sourced fact — it affects only the
Open-vs-Forthcoming display, not the deadline dates themselves, which are
directly quoted from the source page.

Source: https://pacforum.org/fellowships/
        https://pacforum.org/fellowships/lloyd-and-lilian-vasey-fellowship/
        https://pacforum.org/fellowships/james-a-kelly-korea-fellowships/
        https://pacforum.org/fellowships/wsd-handa-fellowship/

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/pacific_forum.py [--dry-run]
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

FUNDER = "Pacific Forum"
DOMAIN = "api_pacific_forum"
PORTAL_GENERAL = "https://pacforum.org/fellowships/"
ORG_NONE: list[str] = []

# Estimated application window — not separately published; affects only the
# Open/Forthcoming threshold, not the (sourced) deadline dates themselves.
OPEN_THRESHOLD_DAYS = 60

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    # ── Lloyd and Lilian Vasey Fellowship ───────────────────────────────────
    {
        "title":    "Lloyd and Lilian Vasey Fellowship — Fall/Winter Cohort",
        "url":      "https://pacforum.org/fellowships/lloyd-and-lilian-vasey-fellowship/",
        "deadline":   datetime.date(2026, 4, 30),
        "desc": (
            "The Vasey Fellowship affords promising scholars from outside "
            "the US the opportunity to serve as researchers at Pacific "
            "Forum, developing hands-on expertise on US-Asia policy issues "
            "and Indo-Pacific economic and security affairs. Resident "
            "fellowships run six months; non-resident fellowships run one "
            "year. This cohort begins in the fall/winter cycle (January 1 "
            "or July 1 start)."
        ),
    },
    {
        "title":    "Lloyd and Lilian Vasey Fellowship — Spring/Summer Cohort",
        "url":      "https://pacforum.org/fellowships/lloyd-and-lilian-vasey-fellowship/",
        "deadline":   datetime.date(2026, 10, 31),
        "desc": (
            "The Vasey Fellowship affords promising scholars from outside "
            "the US the opportunity to serve as researchers at Pacific "
            "Forum, developing hands-on expertise on US-Asia policy issues "
            "and Indo-Pacific economic and security affairs. Resident "
            "fellowships run six months; non-resident fellowships run one "
            "year. This cohort begins in the spring/summer cycle."
        ),
    },
    # ── James A. Kelly Korea Fellowship ─────────────────────────────────────
    {
        "title":    "James A. Kelly Korea Fellowship — Fall/Winter Cohort",
        "url":      "https://pacforum.org/fellowships/james-a-kelly-korea-fellowships/",
        "deadline":   datetime.date(2026, 4, 30),
        "desc": (
            "The James A. Kelly Korean Studies Fellowship promotes "
            "academic study, research, and professional career paths "
            "focused on Korean Peninsula studies, encouraging stronger "
            "US-ROK, US-DPRK, and inter-Korean relations through "
            "participation in Pacific Forum's Young Leaders program and "
            "senior-staff-guided research. Resident fellowships run six "
            "months; non-resident fellowships run one year. This cohort "
            "begins in the fall/winter cycle."
        ),
    },
    {
        "title":    "James A. Kelly Korea Fellowship — Spring/Summer Cohort",
        "url":      "https://pacforum.org/fellowships/james-a-kelly-korea-fellowships/",
        "deadline":   datetime.date(2026, 10, 31),
        "desc": (
            "The James A. Kelly Korean Studies Fellowship promotes "
            "academic study, research, and professional career paths "
            "focused on Korean Peninsula studies, encouraging stronger "
            "US-ROK, US-DPRK, and inter-Korean relations through "
            "participation in Pacific Forum's Young Leaders program and "
            "senior-staff-guided research. Resident fellowships run six "
            "months; non-resident fellowships run one year. This cohort "
            "begins in the spring/summer cycle."
        ),
    },
    # ── WSD-Handa Fellowship ─────────────────────────────────────────────────
    {
        "title":    "WSD-Handa Fellowship — Fall/Winter Cohort",
        "url":      "https://pacforum.org/fellowships/wsd-handa-fellowship/",
        "deadline":   datetime.date(2026, 4, 30),
        "desc": (
            "Funded by the Worldwide Support for Development and Dr. "
            "Handa Haruhisa, the WSD-Handa Fellowship lets young scholars "
            "and professionals examine the political, economic, and "
            "security dynamics of East Asia with a particular focus on "
            "Japan, with priority consideration for applicants from "
            "lesser-developed Southeast Asian nations. Resident fellows "
            "join for six months, non-resident fellows for one year. This "
            "cohort begins in the fall/winter cycle."
        ),
    },
    {
        "title":    "WSD-Handa Fellowship — Spring/Summer Cohort",
        "url":      "https://pacforum.org/fellowships/wsd-handa-fellowship/",
        "deadline":   datetime.date(2026, 10, 31),
        "desc": (
            "Funded by the Worldwide Support for Development and Dr. "
            "Handa Haruhisa, the WSD-Handa Fellowship lets young scholars "
            "and professionals examine the political, economic, and "
            "security dynamics of East Asia with a particular focus on "
            "Japan, with priority consideration for applicants from "
            "lesser-developed Southeast Asian nations. Resident fellows "
            "join for six months, non-resident fellows for one year. This "
            "cohort begins in the spring/summer cycle."
        ),
    },
]

for _s in SCHEMES:
    _s.setdefault("portal", PORTAL_GENERAL)
    _s.setdefault("cycle_years", 1)
    _s.setdefault("open_threshold_days", OPEN_THRESHOLD_DAYS)
    _s.setdefault("amount_min", None)
    _s.setdefault("amount_max", None)
    _s.setdefault("sectors", ["Foreign Policy", "Security Studies"])
    _s.setdefault("individual", ["Researcher", "Early Career Professional"])
    _s.setdefault("grant_types", ["Fellowship"])
    _s.setdefault("org_types", ORG_NONE)
    _s.setdefault("currency", "USD")
    _s.setdefault("applicant_countries", [])
    _s.setdefault("focus_regions", ["Indo-Pacific"])
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
    parser = argparse.ArgumentParser(description="Pacific Forum (Legacy Fellowships) connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    records = [_build_record(s, today) for s in SCHEMES]

    print(f"\n{'─'*70}")
    print(f"  Pacific Forum — {len(records)} scheme(s)  (today: {today})")
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
    print(f"\n  Pacific Forum: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
