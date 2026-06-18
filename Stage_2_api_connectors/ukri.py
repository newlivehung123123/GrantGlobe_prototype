#!/usr/bin/env python3
"""
UKRI funding opportunities connector — Stage 2 API source.

Fetches open funding opportunities from the UKRI Funding Finder.
No API key required. Scrapes the server-rendered HTML listing at
https://www.ukri.org/opportunity/ (paginated, ~10 per page).

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/ukri.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import html
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

UKRI_BASE = "https://www.ukri.org/opportunity/"
UKRI_PAGE = "https://www.ukri.org/opportunity/page/{}/"
MAX_PAGES  = 25   # safety ceiling; real count is ~13

COUNCIL_FUNDER_MAP: dict[str, str] = {
    "AHRC":             "Arts and Humanities Research Council",
    "BBSRC":            "Biotechnology and Biological Sciences Research Council",
    "EPSRC":            "Engineering and Physical Sciences Research Council",
    "ESRC":             "Economic and Social Research Council",
    "Innovate UK":      "Innovate UK",
    "MRC":              "Medical Research Council",
    "NERC":             "Natural Environment Research Council",
    "Research England": "Research England",
    "STFC":             "Science and Technology Facilities Council",
    "UKRI":             "UK Research and Innovation",
}

COUNCIL_SECTOR_MAP: dict[str, list[str]] = {
    "AHRC":             ["Arts & Culture", "Social Sciences & Humanities"],
    "BBSRC":            ["Health Sciences", "Agriculture & Food"],
    "EPSRC":            ["Science & Technology", "Information & Communication Technologies"],
    "ESRC":             ["Social Sciences & Humanities", "Economic Development"],
    "Innovate UK":      ["Technology & Innovation"],
    "MRC":              ["Health Sciences"],
    "NERC":             ["Climate & Environment"],
    "Research England": ["Education & Training", "Research & Innovation"],
    "STFC":             ["Science & Technology"],
    "UKRI":             ["Research & Innovation"],
}


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


def _parse_date(date_str: str | None) -> str | None:
    """Parse UK-style dates like '8 September 2026 4:00pm UK time'."""
    if not date_str:
        return None
    date_str = str(date_str).strip()
    # Remove time portion
    date_str = re.sub(r'\s+\d+:\d+[ap]m.*', '', date_str, flags=re.IGNORECASE).strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _parse_amount(amount_str: str | None) -> float | None:
    """Parse UK monetary strings like '£2,000,000' or '£2 million'."""
    if not amount_str:
        return None
    s = str(amount_str).replace(",", "").replace("£", "").replace("$", "").strip()
    m = re.search(r"([\d.]+)\s*(million|m\b)?", s, re.IGNORECASE)
    if not m:
        return None
    try:
        val = float(m.group(1))
        if m.group(2):
            val *= 1_000_000
        return val
    except ValueError:
        return None


def _fetch_page(session: requests.Session, url: str) -> str | None:
    """Fetch one UKRI listing page; return HTML body or None on error."""
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _parse_opportunities_from_html(html_text: str) -> list[dict]:
    """
    Extract opportunities from a UKRI listing page.

    Actual HTML structure (confirmed from live server):
      <h3 class="entry-title ukri-entry-title">
        <a class="ukri-funding-opp__link" href="https://www.ukri.org/opportunity/slug/">Title</a>
      </h3>
      <div class="entry-content"><p>Description...</p></div>
      <dl class="govuk-table opportunity__summary">
        <div class="govuk-table__row">
          <dt class="govuk-table__header opportunity-cells">Closing date: </dt>
          <dd class="govuk-table__cell opportunity-cells">8 September 2026 4:00pm UK time</dd>
        </div>
        ...
      </dl>
    """
    opps: list[dict] = []

    # Find all opportunity anchor tags by their CSS class
    link_pat = re.compile(
        r'<a\s[^>]*class="[^"]*ukri-funding-opp__link[^"]*"[^>]*href="([^"]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    positions = [(m.start(), m.group(1), m.group(2)) for m in link_pat.finditer(html_text)]

    for i, (pos, url_raw, title_raw) in enumerate(positions):
        # Slice from this link to the next one (or 4000 chars)
        end = positions[i + 1][0] if i + 1 < len(positions) else pos + 4000
        block = html_text[pos:end]
        opp = _extract_fields(url_raw, title_raw, block)
        if opp:
            opps.append(opp)

    return opps


def _strip_tags(s: str) -> str:
    """Remove HTML tags and decode entities."""
    s = re.sub(r'<[^>]+>', ' ', s)
    s = html.unescape(s)
    return re.sub(r'\s+', ' ', s).strip()


def _extract_fields(url_raw: str, title_raw: str, block: str) -> dict | None:
    """
    Extract structured fields from a UKRI opportunity HTML block.

    The actual HTML uses a <dl class="govuk-table opportunity__summary"> table
    with <dt> (field label) / <dd> (field value) pairs, e.g.:
      <dt ...>Closing date: </dt>
      <dd ...>8 September 2026 4:00pm UK time</dd>
    """
    title = _strip_tags(title_raw).strip()
    if not title:
        return None

    portal_url = url_raw.strip()
    if portal_url.startswith("/"):
        portal_url = "https://www.ukri.org" + portal_url

    # ---- Parse <dt>/<dd> pairs from the govuk-table dl ----
    dt_dd_pat = re.compile(
        r'<dt[^>]*>(.*?)</dt>\s*<dd[^>]*>(.*?)</dd>',
        re.DOTALL | re.IGNORECASE,
    )
    fields: dict[str, str] = {}
    for m in dt_dd_pat.finditer(block):
        key = _strip_tags(m.group(1)).strip().rstrip(":").strip().lower()
        val = _strip_tags(m.group(2)).strip()
        if key:
            fields[key] = val

    # ---- Deadline ----
    deadline_raw = fields.get("closing date") or fields.get("close date")
    if deadline_raw and "no closing date" in deadline_raw.lower():
        deadline_raw = None
    deadline_iso = _parse_date(deadline_raw)

    # ---- Opening / publication dates ----
    open_date = _parse_date(fields.get("opening date"))
    pub_date  = _parse_date(fields.get("publication date"))

    # ---- Funder ----
    funders_text = fields.get("funders", "") or fields.get("funder", "")
    council_key = ""
    for key in COUNCIL_FUNDER_MAP:
        if key.lower() in funders_text.lower():
            council_key = key
            break
    funder = COUNCIL_FUNDER_MAP.get(council_key, "UK Research and Innovation")
    thematic_sectors = COUNCIL_SECTOR_MAP.get(council_key, ["Research & Innovation"])

    # ---- Funding amounts ----
    funding_max = _parse_amount(
        fields.get("total fund") or fields.get("maximum award")
    )
    funding_min = None
    range_val = fields.get("award range", "")
    if range_val:
        m_range = re.search(r'([\d,£]+)\s*[-–]\s*([\d,£]+)', range_val)
        if m_range:
            funding_min = _parse_amount(m_range.group(1))
            if not funding_max:
                funding_max = _parse_amount(m_range.group(2))

    # ---- Description: text in entry-content div ----
    m_desc = re.search(
        r'<div[^>]*class="[^"]*entry-content[^"]*"[^>]*>(.*?)</div>',
        block, re.DOTALL | re.IGNORECASE,
    )
    description = _strip_tags(m_desc.group(1)).strip()[:500] if m_desc else None

    slug = re.search(r'/opportunity/([^/?#]+)/?', portal_url)
    opp_id = slug.group(1) if slug else portal_url

    return {
        "url":              portal_url,
        "title":            title,
        "funder":           funder,
        "council_key":      council_key,
        "description":      description,
        "deadline_iso":     deadline_iso,
        "deadline_raw":     deadline_raw,
        "open_date":        open_date,
        "pub_date":         pub_date,
        "funding_min":      funding_min,
        "funding_max":      funding_max,
        "thematic_sectors": thematic_sectors,
        "opp_id":           opp_id,
    }


def _fetch_ukri_opportunities() -> list[dict]:
    """Fetch all UKRI open opportunities by paginating the listing."""
    session = requests.Session()
    session.headers.update({
        "Accept": "text/html,application/xhtml+xml,*/*",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
        "Accept-Language": "en-GB,en;q=0.9",
    })

    all_opps: list[dict] = []

    # Page 1 is at /opportunity/ (no page number)
    for page_num in range(1, MAX_PAGES + 1):
        url = UKRI_BASE if page_num == 1 else UKRI_PAGE.format(page_num)
        html_text = _fetch_page(session, url)
        if not html_text:
            print(f"  UKRI: page {page_num} returned no content — stopping.")
            break

        page_opps = _parse_opportunities_from_html(html_text)
        if not page_opps:
            print(f"  UKRI: page {page_num} yielded 0 opportunities — stopping.")
            break

        all_opps.extend(page_opps)
        print(f"  UKRI page {page_num}: {len(page_opps)} opportunities (total: {len(all_opps)})")

        # Check if there's a next page link in the HTML
        if "next page" not in html_text.lower() and f"page/{page_num + 1}" not in html_text:
            break

        time.sleep(0.5)  # be polite to the server

    return all_opps


def _map_opportunity(opp: dict) -> dict | None:
    """Map one scraped UKRI record to a GrantGlobe grant dict."""
    title = opp.get("title", "").strip()
    portal_url = opp.get("url")
    if not title or not portal_url:
        return None

    return {
        "grant_title":              title,
        "funder_name":              opp.get("funder", "UK Research and Innovation"),
        "source_url":               portal_url,
        "application_portal_url":   portal_url,
        "description":              opp.get("description"),
        "application_deadline":     opp.get("deadline_iso"),
        "application_deadline_raw": opp.get("deadline_raw"),
        "grant_opening_date":       opp.get("open_date"),
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       opp.get("funding_min"),
        "funding_amount_max":       opp.get("funding_max"),
        "currency":                 "GBP" if (opp.get("funding_min") or opp.get("funding_max")) else None,
        "thematic_sectors":         opp.get("thematic_sectors", ["Research & Innovation"]),
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["GB"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_ukri",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{opp.get('opp_id')}|{title}|{opp.get('deadline_iso')}".encode()
        ).hexdigest(),
    }


def _upsert_grant(cur, g: dict) -> str:
    cur.execute(
        "SELECT id, review_status FROM grants WHERE source_url = %s",
        (g["source_url"],)
    )
    existing = cur.fetchone()
    if existing:
        if existing[1] == "rejected":
            return "skipped"
        set_clauses = ", ".join(f"{k} = %({k})s" for k in g if k != "source_url")
        cur.execute(
            f"UPDATE grants SET {set_clauses} WHERE id = %(id)s",
            {**g, "id": existing[0]},
        )
        return "updated"
    cols = list(g.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(f'%({c})s' for c in cols)})",
        g,
    )
    return "inserted"


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(description="UKRI → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching UKRI funding opportunities …")
    raw_opps = _fetch_ukri_opportunities()
    print(f"  {len(raw_opps)} raw records scraped.")

    today = datetime.date.today()
    mapped = []
    for o in raw_opps:
        g = _map_opportunity(o)
        if not g or not g.get("source_url") or not g.get("grant_title"):
            continue
        if g["application_deadline"]:
            try:
                if datetime.date.fromisoformat(g["application_deadline"]) < today:
                    continue
            except ValueError:
                pass
        mapped.append(g)

    seen: set[str] = set()
    deduped = [g for g in mapped if not (g["source_url"] in seen or seen.add(g["source_url"]))]
    print(f"  {len(deduped)} grants to upsert after filtering.")

    if args.dry_run:
        print("\n[DRY RUN] First 3 records:")
        for g in deduped[:3]:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
        return

    conn = _connect()
    try:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        for i in range(0, len(deduped), 200):
            batch = deduped[i: i + 200]
            with conn.cursor() as cur:
                for g in batch:
                    counts[_upsert_grant(cur, g)] += 1
            conn.commit()
            print(f"  Progress: {min(i+200, len(deduped))}/{len(deduped)}")
    finally:
        conn.close()

    print(f"\nDone: {counts['inserted']} inserted, {counts['updated']} updated, "
          f"{counts['skipped']} skipped.")


if __name__ == "__main__":
    main()
