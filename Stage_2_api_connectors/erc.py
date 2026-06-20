#!/usr/bin/env python3
"""
European Research Council (ERC) connector.

The ERC is the EU's primary competitive research funder, disbursing over
€2 billion per year under Horizon Europe to support frontier research across
all disciplines at European host institutions. Researchers of any nationality
may apply; the host institution must be in an EU Member State or Horizon
Europe-associated country.

Schemes covered (5 main grant types):
  - ERC Starting Grant (STG)       — 2–7 years post-PhD; up to €1.5M / 5yr
  - ERC Consolidator Grant (CoG)   — 7–12 years post-PhD; up to €2M / 5yr
  - ERC Advanced Grant (AdG)       — established PIs; up to €2.5M / 5yr
  - ERC Synergy Grant (SyG)        — 2–4 PIs jointly; up to €10M / 6yr
  - ERC Proof of Concept (PoC)     — existing ERC holders only; €150k / 18mo

Call timing pattern (all calls annual):
  - STG: deadline ~October (2026 call closed Oct 2025; 2027 call ~Oct 2026)
  - CoG: deadline ~January (2026 call closed Jan 2026; 2027 call ~Jan 2027)
  - AdG: deadline ~August (2026 call deadline 27 Aug 2026 — OPEN)
  - SyG: deadline ~October (2026 call closed Oct 2025; 2027 call ~Oct 2026)
  - PoC: deadline ~September, two cut-off dates per year (2026 DL1 open)

Live deadline fetching:
  The ERC scheme pages (erc.europa.eu/apply-grant/*) are server-rendered
  (Drupal 10) and embed the current call's deadline in the "Ongoing evaluation"
  or "Open call" sidebar, e.g. "Deadline: 27 August 2026". This connector
  fetches each page and parses that field; for schemes with no upcoming call
  yet listed, it uses pattern-estimated fallback dates.

Excluded / not yet in scope:
  - ERC Plus Grant (new 2026 scheme; details pending)
  - ERC Science Journalism Initiative (not a research grant)
  - ERC for Ukraine (restricted emergency measure)

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/erc.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys
import time

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

FUNDER  = "European Research Council (ERC)"
DOMAIN  = "api_erc"
BASE    = "https://erc.europa.eu"
PORTAL  = ("https://ec.europa.eu/info/funding-tenders/opportunities/portal/"
           "screen/opportunities/calls-for-proposals?"
           "order=DESC&pageSize=50&sortBy=startDate"
           "&status=31094501,31094502"
           "&programmePart=43108406&frameworkProgramme=43108390")

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-GB,en;q=0.9",
}

# ---------------------------------------------------------------------------
# Scheme definitions
# ---------------------------------------------------------------------------

SCHEMES: list[dict] = [
    {
        "title":         "ERC Starting Grant",
        "abbr":          "ERC-STG",
        "url":           f"{BASE}/apply-grant/starting-grant",
        "fallback_next": datetime.date(2026, 10, 15),  # ~mid-Oct annually
        "open_threshold_days": 90,
        "funding_max":   1_500_000,
        "currency":      "EUR",
        "grant_types":   ["Research Grant"],
        "individual":    ["Early Career Researcher", "Postdoctoral Researcher"],
        "org_types":     ["University", "Research Institution"],
        "sectors":       ["Research & Innovation", "Science & Technology",
                          "Health Sciences", "Social Sciences & Humanities"],
        "desc": (
            "ERC Starting Grants support early-career researchers who have "
            "2–7 years of experience since completing their PhD, have already "
            "produced excellent supervised research and are ready to work "
            "independently. Awards of up to €1.5 million for 5 years (with an "
            "optional additional €1 million for exceptional costs such as major "
            "equipment or start-up costs when relocating from a non-associated "
            "third country) are made to a single Principal Investigator who "
            "must be hosted by a public or private research organisation in an "
            "EU Member State or Horizon Europe-associated country. Researchers "
            "of any nationality may apply. Evaluation is based solely on "
            "scientific excellence across 28 disciplinary panels. The call "
            "opens annually in summer with a deadline around October; proposals "
            "are submitted via the EU Funding & Tenders Portal."
        ),
    },
    {
        "title":         "ERC Consolidator Grant",
        "abbr":          "ERC-CoG",
        "url":           f"{BASE}/apply-grant/consolidator-grant",
        "fallback_next": datetime.date(2027, 1, 14),   # ~mid-Jan annually
        "open_threshold_days": 90,
        "funding_max":   2_000_000,
        "currency":      "EUR",
        "grant_types":   ["Research Grant"],
        "individual":    ["Mid-Career Researcher", "Faculty Researcher"],
        "org_types":     ["University", "Research Institution"],
        "sectors":       ["Research & Innovation", "Science & Technology",
                          "Health Sciences", "Social Sciences & Humanities"],
        "desc": (
            "ERC Consolidator Grants support mid-career researchers with 7–12 "
            "years of experience since their PhD who wish to consolidate their "
            "independence and strengthen a recently established research team. "
            "Awards of up to €2 million for 5 years (with an optional additional "
            "€1 million for exceptional costs) are made to a single Principal "
            "Investigator at an eligible host institution in an EU Member State "
            "or Horizon Europe-associated country. Researchers of any nationality "
            "may apply. Evaluation is based solely on scientific excellence. The "
            "call opens annually in autumn with a deadline around January; "
            "proposals are submitted via the EU Funding & Tenders Portal."
        ),
    },
    {
        "title":         "ERC Advanced Grant",
        "abbr":          "ERC-AdG",
        "url":           f"{BASE}/apply-grant/advanced-grant",
        "fallback_next": datetime.date(2026, 8, 27),   # confirmed 2026 deadline
        "open_threshold_days": 90,
        "funding_max":   2_500_000,
        "currency":      "EUR",
        "grant_types":   ["Research Grant"],
        "individual":    ["Faculty Researcher", "Senior Researcher"],
        "org_types":     ["University", "Research Institution"],
        "sectors":       ["Research & Innovation", "Science & Technology",
                          "Health Sciences", "Social Sciences & Humanities"],
        "desc": (
            "ERC Advanced Grants support established, leading research leaders "
            "with a track record of significant scientific achievements who wish "
            "to pursue ground-breaking, high-risk/high-gain research. No specific "
            "career-stage eligibility window applies — exceptional PIs at any "
            "senior stage may apply. Awards of up to €2.5 million for 5 years "
            "(with up to an additional €2 million for exceptional costs including "
            "start-up costs for PIs relocating from a third country) are made to "
            "a single PI at an eligible host institution in an EU Member State or "
            "Horizon Europe-associated country. Researchers of any nationality "
            "may apply. Advanced Grants are implemented under a lump-sum funding "
            "model from the 2024 call onwards. The 2026 call (ERC-2026-ADG) "
            "opened on 28 May 2026 with a submission deadline of 27 August 2026. "
            "Proposals are submitted via the EU Funding & Tenders Portal."
        ),
    },
    {
        "title":         "ERC Synergy Grant",
        "abbr":          "ERC-SyG",
        "url":           f"{BASE}/apply-grant/synergy-grant",
        "fallback_next": datetime.date(2026, 10, 20),  # ~Oct annually
        "open_threshold_days": 90,
        "funding_max":   10_000_000,
        "currency":      "EUR",
        "grant_types":   ["Research Grant"],
        "individual":    ["Faculty Researcher", "Senior Researcher",
                          "Mid-Career Researcher", "Early Career Researcher"],
        "org_types":     ["University", "Research Institution"],
        "sectors":       ["Research & Innovation", "Science & Technology",
                          "Health Sciences", "Social Sciences & Humanities"],
        "desc": (
            "ERC Synergy Grants fund groups of two to four Principal Investigators "
            "working together to address ambitious research problems that cannot "
            "be tackled by a single PI alone. At least one PI must be hosted at "
            "an institution in an EU Member State or Horizon Europe-associated "
            "country; one PI may be hosted outside the EU/associated countries. "
            "Awards of up to €10 million for 6 years (with up to €4 million "
            "additional for exceptional costs) are evaluated on scientific "
            "excellence and outstanding synergetic effect through a three-step "
            "process including an interview. Researchers of any nationality and "
            "career stage may apply; no specific academic criteria are required. "
            "The call opens annually in summer with a deadline around October; "
            "proposals are submitted via the EU Funding & Tenders Portal."
        ),
    },
    {
        "title":         "ERC Proof of Concept Grant",
        "abbr":          "ERC-PoC",
        "url":           f"{BASE}/apply-grant/proof-concept",
        "fallback_next": datetime.date(2026, 9, 17),   # confirmed 2026 deadline
        "open_threshold_days": 120,  # PoC call is open ~4 months
        "funding_max":   150_000,
        "currency":      "EUR",
        "grant_types":   ["Research Grant"],
        "individual":    ["Faculty Researcher", "Senior Researcher",
                          "Mid-Career Researcher", "Early Career Researcher"],
        "org_types":     ["University", "Research Institution"],
        "sectors":       ["Research & Innovation", "Science & Technology",
                          "Health Sciences", "Social Sciences & Humanities"],
        "desc": (
            "ERC Proof of Concept Grants help ERC-funded researchers (holders of "
            "a current or recently ended ERC Starting, Consolidator, Advanced, or "
            "Synergy Grant) explore the commercial or societal potential of their "
            "frontier research. Awards are a lump sum of €150,000 for 18 months, "
            "covering activities such as testing, validation, IP protection "
            "strategy, and stakeholder engagement. Only PIs holding an active "
            "ERC main grant or a grant that ended after 1 January 2025 are "
            "eligible; a maximum of three PoC grants may be awarded per main "
            "grant project. Applications are evaluated on breakthrough innovation "
            "potential, approach/methodology, and PI strategic lead in a single-"
            "stage process. From 2024, calls have two cut-off dates per year. "
            "The 2026 call (ERC-2026-PoC) deadline is 17 September 2026. "
            "Proposals are submitted via the EU Funding & Tenders Portal."
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


def _fetch(url: str, timeout: int = 30) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = "utf-8"
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _strip_tags(html: str) -> str:
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    return re.sub(r'\s+', ' ', html).strip()


def _parse_date_str(text: str) -> datetime.date | None:
    """Parse an English-format date string (e.g. '27 August 2026')."""
    text = re.sub(r'(\d+)(?:st|nd|rd|th)\b', r'\1', text.strip())
    text = re.sub(r'\s+', ' ', text).strip()
    # Strip trailing parenthetical e.g. "(17.00 Brussels time)"
    text = re.sub(r'\(.*\)', '', text).strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%B %d, %Y", "%B %d %Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _find_upcoming_deadline(html: str, today: datetime.date) -> datetime.date | None:
    """
    Parse the first future 'Deadline: ...' date from an ERC scheme page.
    Pages are server-rendered Drupal; the pattern appears in the sidebar:
      "Deadline: 27 August 2026" or "Deadline: 17 September 2026 (17.00 ...)"
    """
    text = _strip_tags(html)

    # Pattern: Deadline: D Month YYYY
    months = (
        r'(?:January|February|March|April|May|June|July|August|'
        r'September|October|November|December|'
        r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
    )
    pat = rf'[Dd]eadline\s*:\s*(\d{{1,2}}\s+{months}\s+\d{{4}}[^|]*?(?:\([\w\s:.]+\))?)'
    for m in re.finditer(pat, text):
        raw = m.group(1).strip()
        d = _parse_date_str(raw)
        if d and d >= today:
            return d

    # Also try ISO format deadlines: YYYY-MM-DD
    for m in re.finditer(r'\b(\d{4}-\d{2}-\d{2})\b', text):
        try:
            d = datetime.date.fromisoformat(m.group(1))
            if d >= today:
                return d
        except ValueError:
            continue

    return None


def _advance_fallback(est: datetime.date, today: datetime.date) -> datetime.date:
    """If fallback date has passed, advance by 1 year."""
    if est < today:
        try:
            return est.replace(year=est.year + 1)
        except ValueError:
            return datetime.date(est.year + 1, est.month, 28)
    return est


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_record(scheme: dict, deadline: datetime.date, status: str) -> dict:
    today = datetime.date.today()
    deadline_iso = deadline.isoformat()
    deadline_raw = str(deadline.day) + " " + deadline.strftime("%B %Y")

    return {
        "grant_title":              scheme["title"],
        "funder_name":              FUNDER,
        "source_url":               scheme["url"],
        "application_portal_url":   PORTAL,
        "description":              scheme["desc"],
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       None,
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       scheme.get("funding_max"),
        "currency":                 scheme.get("currency"),
        "thematic_sectors":         scheme["sectors"],
        "grant_types":              scheme["grant_types"],
        "applicant_base_regions":   ["Global"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": [],
        "geographic_focus_countries": [],
        "organisation_types":       scheme["org_types"],
        "individual_eligibility":   scheme["individual"],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(scheme["url"], scheme["title"], deadline_iso),
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s", (record["source_url"],))
    existing = cur.fetchone()
    if existing:
        _upd_cols = [c for c in record if c != "source_url"]
        _set_clause = ", ".join(f"{c} = %({c})s" for c in _upd_cols)
        cur.execute(
            f"UPDATE grants SET {_set_clause} WHERE id = %(id)s",
            {**record, "id": existing[0]},
        )
        return "updated"
    cols = list(record.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})",
        [record[c] for c in cols],
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="European Research Council connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    parser.add_argument("--skip-fetch", action="store_true",
                        help="Skip live page fetch; use fallback dates only")
    args = parser.parse_args()

    today = datetime.date.today()
    records: list[dict] = []

    for scheme in SCHEMES:
        title = scheme["title"]
        print(f"  Fetching {title} …")

        deadline: datetime.date | None = None
        src = "fallback"

        if not args.skip_fetch:
            html = _fetch(scheme["url"])
            if html:
                deadline = _find_upcoming_deadline(html, today)
                if deadline:
                    src = "live"
            time.sleep(1)

        # Resolve final deadline
        if deadline and deadline >= today:
            final_deadline = deadline
        else:
            final_deadline = _advance_fallback(scheme["fallback_next"], today)
            src = "pattern" if src == "live" else "fallback"

        # Determine status
        days_until = (final_deadline - today).days
        status = "Open" if days_until <= scheme["open_threshold_days"] else "Forthcoming"

        rec = _build_record(scheme, final_deadline, status)
        records.append(rec)
        print(f"    [{status:12s}] → {final_deadline}  ({src}, {days_until}d)")

    print(f"\n  Total: {len(records)} records")
    for r in records:
        print(f"  [{r['current_status']:12s}] {r['grant_title'][:65]}  → {r['application_deadline']}")

    if args.dry_run:
        print("\n[DRY RUN] Full records:")
        for r in records:
            print(json.dumps(r, indent=2, default=str))
        return

    conn = _connect()
    inserted = updated = err = 0
    for record in records:
        try:
            result = _upsert(conn, record)
            conn.commit()
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            conn.rollback()
            print(f"  DB error [{record['grant_title'][:50]}]: {e}")
            err += 1
    conn.close()
    print(f"\nDone: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
