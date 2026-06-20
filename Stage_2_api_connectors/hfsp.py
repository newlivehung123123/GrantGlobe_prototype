#!/usr/bin/env python3
"""
HFSP (Human Frontier Science Program) connector.

HFSP funds frontier, interdisciplinary basic research in the life sciences,
implemented by the International Human Frontier Science Program Organization
(HFSPO) based in Strasbourg.

Programs covered:
  - Research Grants (Early Career and Program)
  - Postdoctoral Fellowships (Long-Term and Cross-Disciplinary)

Annual cycle:
  - Research Grants LOI: ~late March each year
  - Research Grants Full Proposal: ~mid-September (invite-only)
  - Postdoctoral Fellowship LOI: ~mid-May each year
  - Postdoctoral Fellowship Full Proposal: ~late September (invite-only)

The site is server-rendered Drupal — pages are directly fetchable.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/hfsp.py [--dry-run]
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

RESEARCH_GRANTS_URL = "https://www.hfsp.org/funding/hfsp-funding/research-grants"
FELLOWSHIPS_URL     = "https://www.hfsp.org/funding/hfsp-funding/postdoctoral-fellowships"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

FUNDER = "Human Frontier Science Program (HFSP)"
DOMAIN = "api_hfsp"

# Month pattern for date regex
_MONTHS = (
    r'(?:January|February|March|April|May|June|July|August|'
    r'September|October|November|December|'
    r'Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Oct|Nov|Dec)'
)
# Matches "September 24, 2026" or "24 September 2026" or "24th March 2026"
_DATE_PAT = (
    rf'(?:\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTHS}\s+\d{{4}}'
    rf'|{_MONTHS}\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}})'
)


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


def _fetch(url: str) -> str:
    resp = requests.get(url, headers=HEADERS, timeout=30)
    resp.raise_for_status()
    resp.encoding = "utf-8"
    return resp.text


def _strip_tags(html: str) -> str:
    html = re.sub(r'<!--.*?-->', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = re.sub(r'&nbsp;', ' ', html)
    html = re.sub(r'&amp;', '&', html)
    return re.sub(r'\s+', ' ', html).strip()


def _parse_date_str(text: str) -> datetime.date | None:
    """Parse a date string in various natural-language formats."""
    text = re.sub(r'\s+', ' ', text.strip())
    # Strip ordinal suffixes: "26th" → "26"
    text = re.sub(r'(\d+)(?:st|nd|rd|th)\b', r'\1', text)
    for fmt in (
        "%B %d, %Y", "%B %d %Y",
        "%d %B %Y",  "%d %b %Y",
        "%b %d, %Y", "%b %d %Y",
        "%Y-%m-%d",
    ):
        try:
            return datetime.datetime.strptime(text.strip(), fmt).date()
        except ValueError:
            continue
    return None


def _find_deadline(text: str, keyword_re: str) -> datetime.date | None:
    """Find the first date following a keyword pattern in plain text."""
    m = re.search(
        keyword_re + r'.{0,250}?(' + _DATE_PAT + r')',
        text,
        re.IGNORECASE | re.DOTALL,
    )
    if m:
        return _parse_date_str(m.group(1))
    return None


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


# ---------------------------------------------------------------------------
# Page parsers
# ---------------------------------------------------------------------------

def _parse_research_grants(html: str, today: datetime.date) -> list[dict]:
    text = _strip_tags(html)
    records: list[dict] = []
    next_year = today.year + 1

    # LOI deadline
    loi_date = _find_deadline(text, r'[Ll]etter\s+of\s+[Ii]ntent')

    # Full proposal deadline — often stated approximately ("around mid-September YYYY")
    fp_date = _find_deadline(text, r'[Ff]ull\s+[Pp]roposal')
    if not fp_date:
        # Fallback: "mid-September YYYY" / "mid September YYYY"
        m = re.search(
            r'mid.{0,5}(September|October)\s+(\d{4})', text, re.IGNORECASE
        )
        if m:
            month = 9 if m.group(1).lower() == 'september' else 10
            try:
                fp_date = datetime.date(int(m.group(2)), month, 15)
            except ValueError:
                pass

    # Add "Open" LOI record if LOI deadline is still upcoming
    if loi_date and loi_date >= today:
        records.append(_build_grant_record(
            title="HFSP Research Grants – Letter of Intent",
            url=RESEARCH_GRANTS_URL,
            deadline=loi_date,
            status="Open",
            desc=(
                "HFSP Research Grants support novel, interdisciplinary collaborations in the "
                "life sciences across international teams from HFSP member countries. Two "
                "categories: Early Career Grants (teams with no senior PI having held an "
                "independent lab for more than 5 years) and Program Grants (more senior teams). "
                "First stage: Letter of Intent submitted via ProposalCentral."
            ),
            grant_types=["Research Grant"],
            individual_eligibility=[],
        ))

    # Add "Invitation Only" Full Proposal record if deadline is upcoming
    if fp_date and fp_date >= today:
        records.append(_build_grant_record(
            title="HFSP Research Grants – Full Proposal (by invitation)",
            url=RESEARCH_GRANTS_URL + "#full-proposal",
            deadline=fp_date,
            status="Invitation Only",
            desc=(
                "HFSP Research Grants full proposal stage. Only teams invited after the LOI "
                "review may submit a full proposal. Awards fund collaborative international "
                "teams (≥ 2 countries) working on basic research at the frontier of the life "
                "sciences. Funding: up to USD 450,000 over 3 years for Early Career grants; "
                "up to USD 600,000 for Program grants. Submitted via ProposalCentral."
            ),
            grant_types=["Research Grant"],
            individual_eligibility=[],
        ))

    # Add "Forthcoming" next-cycle LOI if current-cycle LOI has already closed
    if not loi_date or loi_date < today:
        # Estimate next cycle: same calendar date, next year
        if loi_date:
            try:
                next_loi = datetime.date(next_year, loi_date.month, loi_date.day)
            except ValueError:
                next_loi = datetime.date(next_year, 3, 26)  # typical date
        else:
            next_loi = datetime.date(next_year, 3, 26)

        records.append(_build_grant_record(
            title="HFSP Research Grants – Letter of Intent (next annual cycle)",
            url=RESEARCH_GRANTS_URL + "#next-cycle",
            deadline=next_loi,
            status="Forthcoming",
            desc=(
                "HFSP Research Grants support international collaborative teams conducting "
                "frontier basic research in the life sciences. LOI deadline is typically in "
                "late March each year. This estimated date is based on the previous cycle; "
                "the application portal opens in late January — verify at hfsp.org. "
                "Member countries: AU, CA, EU, FR, DE, IN, IL, IT, JP, KR, NZ, NO, SG, ZA, CH, GB, US."
            ),
            grant_types=["Research Grant"],
            individual_eligibility=[],
        ))

    return records


def _parse_fellowships(html: str, today: datetime.date) -> list[dict]:
    text = _strip_tags(html)
    records: list[dict] = []
    next_year = today.year + 1

    # LOI deadline
    loi_date = _find_deadline(text, r'[Ll]etter\s+of\s+[Ii]ntent')

    # Full Proposal deadline (specific date, usually late September)
    fp_date = _find_deadline(text, r'[Ff]ull\s+[Pp]roposal')

    # Add "Open" LOI if upcoming
    if loi_date and loi_date >= today:
        records.append(_build_grant_record(
            title="HFSP Postdoctoral Fellowships – Letter of Intent",
            url=FELLOWSHIPS_URL,
            deadline=loi_date,
            status="Open",
            desc=(
                "HFSP Postdoctoral Fellowships support early career researchers moving to a new "
                "country and a new area of basic life sciences research. Two fellowship types: "
                "Long-Term Fellowship (LTF) for applicants with a biology PhD, and "
                "Cross-Disciplinary Fellowship (CDF) for PhD holders from outside biology "
                "(physics, chemistry, mathematics, engineering, computer science). LOI stage "
                "via ProposalCentral; portal typically opens in March."
            ),
            grant_types=["Fellowship"],
            individual_eligibility=["Postdoctoral Researcher"],
        ))

    # Add "Invitation Only" Full Proposal if upcoming
    if fp_date and fp_date >= today:
        records.append(_build_grant_record(
            title="HFSP Postdoctoral Fellowships – Full Proposal (by invitation)",
            url=FELLOWSHIPS_URL + "#full-proposal",
            deadline=fp_date,
            status="Invitation Only",
            desc=(
                "HFSP Postdoctoral Fellowships full proposal stage (by invitation only). "
                "Approximately the top 15–20% of eligible LOIs are invited to submit a full "
                "proposal. Notification of LOI results is typically sent mid-August. Covers "
                "both Long-Term Fellowships (LTF) and Cross-Disciplinary Fellowships (CDF). "
                "Fellowships are for 3 years; fellows must begin between 1 April and 1 January "
                "of the following year. Submitted via ProposalCentral."
            ),
            grant_types=["Fellowship"],
            individual_eligibility=["Postdoctoral Researcher"],
        ))

    # Add "Forthcoming" next-cycle LOI if current LOI has closed
    if not loi_date or loi_date < today:
        if loi_date:
            try:
                next_loi = datetime.date(next_year, loi_date.month, loi_date.day)
            except ValueError:
                next_loi = datetime.date(next_year, 5, 12)  # typical date
        else:
            next_loi = datetime.date(next_year, 5, 12)

        records.append(_build_grant_record(
            title="HFSP Postdoctoral Fellowships – Letter of Intent (next annual cycle)",
            url=FELLOWSHIPS_URL + "#next-cycle",
            deadline=next_loi,
            status="Forthcoming",
            desc=(
                "HFSP Postdoctoral Fellowships for early career researchers in basic life sciences. "
                "LOI deadline is typically in mid-May each year; the portal opens in March. "
                "Applicants must propose a new country and a research direction clearly distinct "
                "from their PhD work. Open to applicants of any nationality (with host country "
                "and eligibility rules — see hfsp.org). "
                "This estimated date is based on the previous cycle."
            ),
            grant_types=["Fellowship"],
            individual_eligibility=["Postdoctoral Researcher"],
        ))

    return records


# ---------------------------------------------------------------------------
# Record builder
# ---------------------------------------------------------------------------

def _build_grant_record(
    title: str,
    url: str,
    deadline: datetime.date | None,
    status: str,
    desc: str,
    grant_types: list[str],
    individual_eligibility: list[str],
) -> dict:
    today = datetime.date.today()
    deadline_iso = deadline.isoformat() if deadline else None
    deadline_raw = (
        str(deadline.day) + " " + deadline.strftime("%B %Y")
        if deadline else None
    )
    return {
        "grant_title":              title,
        "funder_name":              FUNDER,
        "source_url":               url,
        "application_portal_url":   "https://proposalcentral.com/",
        "description":              desc,
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       None,
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         ["Health Sciences", "Research & Innovation"],
        "grant_types":              grant_types,
        "applicant_base_regions":   ["Global"],
        "geographic_focus_regions": ["Global"],
        "applicant_base_countries": [],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   individual_eligibility,
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(url, title, deadline_iso or ""),
    }


# ---------------------------------------------------------------------------
# DB upsert
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM grants WHERE source_url = %s",
        (record["source_url"],)
    )
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
    parser = argparse.ArgumentParser(description="HFSP connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    today = datetime.date.today()
    all_records: list[dict] = []

    print("Fetching HFSP Research Grants page …")
    try:
        html = _fetch(RESEARCH_GRANTS_URL)
        rg = _parse_research_grants(html, today)
        print(f"  Parsed {len(rg)} Research Grant record(s).")
        all_records.extend(rg)
    except Exception as e:
        print(f"  ERROR: {e}")

    time.sleep(1)

    print("Fetching HFSP Postdoctoral Fellowships page …")
    try:
        html = _fetch(FELLOWSHIPS_URL)
        fel = _parse_fellowships(html, today)
        print(f"  Parsed {len(fel)} Fellowship record(s).")
        all_records.extend(fel)
    except Exception as e:
        print(f"  ERROR: {e}")

    print(f"\n  Total: {len(all_records)} records")
    for r in all_records:
        print(f"  [{r['current_status']:20s}] {r['grant_title'][:60]}  → {r['application_deadline']}")

    if args.dry_run:
        print("\n[DRY RUN] Full records:")
        for r in all_records:
            print(json.dumps(r, indent=2, default=str))
        return

    conn = _connect()
    inserted = updated = err = 0
    for record in all_records:
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
