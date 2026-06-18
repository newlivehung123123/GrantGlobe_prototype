#!/usr/bin/env python3
"""
Research Council of Finland (AKA) connector — Stage 2 API source.

Scrapes open calls from aka.fi/en/research-funding/apply-for-funding/calls-for-applications/.
No API key required. Server-rendered HTML.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/finland_aka.py [--dry-run]
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

AKA_BASE     = "https://www.aka.fi"
AKA_LIST_URL = (
    "https://www.aka.fi/en/research-funding/apply-for-funding/calls-for-applications/"
)

DOMAIN_SECTOR_MAP: dict[str, list[str]] = {
    "health":            ["Health Sciences"],
    "medical":           ["Health Sciences"],
    "brain":             ["Health Sciences"],
    "cancer":            ["Health Sciences"],
    "climate":           ["Climate & Environment"],
    "environment":       ["Climate & Environment"],
    "ocean":             ["Climate & Environment"],
    "water":             ["Climate & Environment"],
    "biodiversity":      ["Climate & Environment"],
    "energy":            ["Climate & Environment", "Science & Technology"],
    "technology":        ["Science & Technology", "Technology & Innovation"],
    "digital":           ["Science & Technology", "Technology & Innovation"],
    "computing":         ["Science & Technology"],
    "quantum":           ["Science & Technology", "Technology & Innovation"],
    "artificial intelligence": ["Science & Technology", "Technology & Innovation"],
    "innovation":        ["Technology & Innovation"],
    "social":            ["Social Sciences & Humanities"],
    "humanities":        ["Social Sciences & Humanities"],
    "education":         ["Education & Training"],
    "security":          ["Defence & Security"],
    "agriculture":       ["Agriculture & Food"],
    "materials":         ["Science & Technology"],
    "physics":           ["Science & Technology"],
    "mathematics":       ["Science & Technology"],
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


def _strip_tags(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def _parse_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    date_str = re.sub(r"\s+", " ", str(date_str)).strip()
    # Strip time suffixes: "at 23.59 Finnish time", "at 16:00"
    date_str = re.sub(r"\s+at\s+\d+[:.]\d+.*$", "", date_str, flags=re.IGNORECASE).strip()
    date_str = re.sub(r",?\s*\d+:\d+.*", "", date_str).strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%B %d, %Y",
                "%d/%m/%Y", "%d.%m.%Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _infer_sectors(text: str) -> list[str]:
    text_lower = text.lower()
    sectors: list[str] = []
    for keyword, sector_list in DOMAIN_SECTOR_MAP.items():
        if keyword in text_lower:
            sectors.extend(s for s in sector_list if s not in sectors)
    return sectors or ["Research & Innovation"]


def _fetch_page(session: requests.Session, url: str) -> str | None:
    try:
        resp = session.get(url, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


# AKA link pattern: individual call pages under calls-for-applications
_LINK_PAT = re.compile(
    r'<a\s[^>]*href="'
    r'(/en/research-funding/apply-for-funding/calls-for-applications/[^"?#]+)"'
    r'[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)

# Date label patterns: "Call opens DD Mon YYYY" / "Call closes DD Mon YYYY"
_OPENS_PAT = re.compile(
    r"call\s+opens?\s+[^<]{0,10}?"
    r"(\d{1,2}\s+\w+\s+\d{4}|\w+\s+\d{4})",
    re.IGNORECASE,
)
_CLOSES_PAT = re.compile(
    r"call\s+closes?\s+[^<]{0,10}?"
    r"(\d{1,2}\s+(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{4})",
    re.IGNORECASE,
)


def _parse_calls_from_html(html_text: str) -> list[dict]:
    """
    Extract open calls from the AKA listing HTML.

    AKA's page has a clear structure:
      <h3><a href="/en/.../calls-for-applications/{section}/{slug}/">Title</a></h3>
      <p><strong>Call opens</strong> DD Mon YYYY</p>
      <p><strong>Call closes</strong> DD Mon YYYY</p>

    The "In preparation" section should be excluded (no firm open date / no live link).
    We stop processing once we pass the "In preparation" heading.
    """
    opps: list[dict] = []
    seen_urls: set[str] = set()

    # Find the position of "In preparation" heading to stop scraping there
    in_prep_pos = html_text.lower().find("in preparation")
    if in_prep_pos == -1:
        in_prep_pos = len(html_text)

    # Work only on the section before "In preparation"
    active_html = html_text[:in_prep_pos]

    for m in _LINK_PAT.finditer(active_html):
        href_raw  = m.group(1).strip()
        title_raw = _strip_tags(m.group(2)).strip()

        if not title_raw or len(title_raw) < 5:
            continue
        # Skip the listing page URL itself and breadcrumb-style links
        if href_raw.rstrip("/") == "/en/research-funding/apply-for-funding/calls-for-applications":
            continue
        # Skip navigation / category listing links (no sub-slug beyond the category)
        parts = [p for p in href_raw.strip("/").split("/") if p]
        # calls-for-applications/{category}/{slug} → need at least 6 path parts
        if len(parts) < 6:
            continue

        url = f"{AKA_BASE}{href_raw}"
        if url in seen_urls:
            continue
        seen_urls.add(url)

        pos   = m.start()
        block = html_text[pos: pos + 1500]

        # Strip HTML tags from the block before searching for date labels.
        # The AKA page wraps "Call opens"/"Call closes" in <strong> tags, so a raw
        # HTML search sees e.g. "closes</strong> 14 Oct 2026" which breaks [^<] patterns.
        block_text = _strip_tags(block)

        # Deadline ("Call closes")
        deadline_iso = None
        deadline_raw = None
        cm = _CLOSES_PAT.search(block_text)
        if cm:
            deadline_raw = cm.group(1).strip()
            # Handle "Nov 2026" (no day given) → first of month
            if not re.search(r"^\d{1,2}\s", deadline_raw):
                deadline_raw = f"1 {deadline_raw}"
            deadline_iso = _parse_date(deadline_raw)

        # Open date ("Call opens")
        open_date_iso = None
        om = _OPENS_PAT.search(block_text)
        if om:
            raw = om.group(1).strip()
            if not re.search(r"^\d{1,2}\s", raw):
                raw = f"1 {raw}"
            open_date_iso = _parse_date(raw)

        # Description: first <p> that isn't just a date label
        description = None
        for dm in re.finditer(r"<p[^>]*>(.*?)</p>", block, re.DOTALL | re.IGNORECASE):
            text = _strip_tags(dm.group(1)).strip()
            if text and not text.lower().startswith("call ") and len(text) > 20:
                description = text[:400]
                break

        slug = re.search(r"/([^/?#]+)/?$", href_raw)
        opp_id = slug.group(1) if slug else href_raw

        opps.append({
            "title":          title_raw,
            "url":            url,
            "opp_id":         opp_id,
            "open_date_iso":  open_date_iso,
            "deadline_iso":   deadline_iso,
            "deadline_raw":   deadline_raw,
            "description":    description,
        })

    return opps


def _fetch_aka_opportunities() -> list[dict]:
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

    html_text = _fetch_page(session, AKA_LIST_URL)
    if not html_text:
        print("  AKA: listing page returned no content.")
        return []

    idx = html_text.find("/en/research-funding/apply-for-funding/calls-for-applications/")
    if idx > 0:
        print(f"  AKA: first call link at char {idx} ✓")
    else:
        print("  AKA WARNING: no call links found — site may be JS-rendered")
        print(f"  AKA page length: {len(html_text)} chars")
        print(f"  AKA snippet (2000-3500): {html_text[2000:3500]}")

    opps = _parse_calls_from_html(html_text)
    print(f"  AKA: {len(opps)} open calls parsed from listing page.")
    return opps


def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url   = opp.get("url", "").strip()
    if not title or not url:
        return None

    return {
        "grant_title":              title,
        "funder_name":              "Research Council of Finland",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              opp.get("description"),
        "application_deadline":     opp.get("deadline_iso"),
        "application_deadline_raw": opp.get("deadline_raw"),
        "grant_opening_date":       opp.get("open_date_iso"),
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         _infer_sectors(
            (title or "") + " " + (opp.get("description") or "")
        ),
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["FI"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_aka_finland",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{opp.get('opp_id') or url}|{title}|{opp.get('deadline_iso')}".encode()
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
    parser = argparse.ArgumentParser(description="Research Council of Finland → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching Research Council of Finland open calls …")
    raw_opps = _fetch_aka_opportunities()
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
        with conn.cursor() as cur:
            for g in deduped:
                counts[_upsert_grant(cur, g)] += 1
        conn.commit()
    finally:
        conn.close()

    print(f"\nDone: {counts['inserted']} inserted, {counts['updated']} updated, "
          f"{counts['skipped']} skipped.")


if __name__ == "__main__":
    main()
