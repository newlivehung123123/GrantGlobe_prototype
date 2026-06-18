#!/usr/bin/env python3
"""
NCN Poland (Narodowe Centrum Nauki) connector — Stage 2 API source.

Scrapes open competitions from the NCN "Otwarte konkursy" sidebar.
Drupal 9, server-rendered HTML. No API key required.

The sidebar listing all currently open competitions appears on every NCN page.
We use the competition schedule page as a stable seed URL.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/poland_ncn.py [--dry-run]
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

NCN_BASE     = "https://ncn.gov.pl"
# Stable seed page that always carries the "Otwarte konkursy" sidebar
NCN_SEED_URL = "https://ncn.gov.pl/finansowanie-nauki/konkursy/harmonogram"
# Competition detail pages follow this pattern
NCN_COMP_URL = "https://ncn.gov.pl/ogloszenia/konkursy/{slug}"

# Polish abbreviated month names → month number
PL_MONTHS = {
    "sty": 1,  # styczeń  (January)
    "lut": 2,  # luty     (February)
    "mar": 3,  # marzec   (March)
    "kwi": 4,  # kwiecień (April)
    "maj": 5,  # maj      (May)
    "cze": 6,  # czerwiec (June)
    "lip": 7,  # lipiec   (July)
    "sie": 8,  # sierpień (August)
    "wrz": 9,  # wrzesień (September)
    "paź": 10, # październik (October)
    "paz": 10, # alternative without diacritic
    "lis": 11, # listopad (November)
    "gru": 12, # grudzień (December)
}

# Long Polish month names (appear in body text deadlines)
PL_MONTHS_LONG = {
    "stycznia": 1, "lutego": 2, "marca": 3, "kwietnia": 4,
    "maja": 5, "czerwca": 6, "lipca": 7, "sierpnia": 8,
    "września": 9, "wrzesnia": 9, "października": 10, "pazdziernika": 10,
    "listopada": 11, "grudnia": 12,
}

TOPIC_SECTOR_MAP: dict[str, list[str]] = {
    "hs":   ["Social Sciences & Humanities"],
    "st":   ["Science & Technology"],
    "nz":   ["Health Sciences"],
    "life": ["Health Sciences"],
    "humanities": ["Social Sciences & Humanities"],
    "social": ["Social Sciences & Humanities"],
    "science": ["Science & Technology"],
    "technology": ["Science & Technology"],
    "innovation": ["Technology & Innovation"],
    "medical": ["Health Sciences"],
    "health": ["Health Sciences"],
    "climate": ["Climate & Environment"],
    "education": ["Education & Training"],
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


def _parse_pl_sidebar_date(date_str: str) -> str | None:
    """
    Parse a Polish sidebar date like "31 lip" or "8 lip" into ISO 8601.
    The year is inferred: current year if month >= today's month, else next year.
    """
    if not date_str:
        return None
    m = re.match(r"(\d{1,2})\s+([a-zA-Zźąśęóńłćżó]+)", date_str.strip(), re.UNICODE)
    if not m:
        return None
    day        = int(m.group(1))
    month_abbr = m.group(2).lower().strip()

    # Normalise: strip trailing 'a' (genitive forms) if needed
    month_num = PL_MONTHS.get(month_abbr[:3]) or PL_MONTHS.get(month_abbr)
    if not month_num:
        return None

    today = datetime.date.today()
    year  = today.year if month_num >= today.month else today.year + 1
    # Handle edge case: same month but day already passed
    if month_num == today.month and day < today.day:
        year = today.year + 1

    try:
        return datetime.date(year, month_num, day).isoformat()
    except ValueError:
        return None


def _parse_pl_body_deadline(text: str) -> str | None:
    """
    Extract deadline from Polish competition body text.
    Looks for: "do DD miesiąc RRRR r." patterns.
    """
    # "do 31 lipca 2026 r."
    months = "|".join(PL_MONTHS_LONG.keys())
    m = re.search(
        rf"\bdo\s+(\d{{1,2}})\s+({months})\s+(20\d{{2}})",
        text, re.IGNORECASE | re.UNICODE,
    )
    if m:
        day       = int(m.group(1))
        month_num = PL_MONTHS_LONG.get(m.group(2).lower())
        year      = int(m.group(3))
        if month_num:
            try:
                return datetime.date(year, month_num, day).isoformat()
            except ValueError:
                pass

    # "31.12.2026"
    m = re.search(r"\b(\d{2})\.(\d{2})\.(20\d{2})\b", text)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    return None


def _infer_sectors(text: str) -> list[str]:
    text_lower = text.lower()
    sectors: list[str] = []
    for keyword, sector_list in TOPIC_SECTOR_MAP.items():
        if keyword in text_lower:
            sectors.extend(s for s in sector_list if s not in sectors)
    return sectors or ["Research & Innovation"]


def _fetch_page(session: requests.Session, url: str) -> str | None:
    try:
        resp = session.get(url, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _parse_sidebar(html_text: str) -> list[dict]:
    """
    Extract open competitions from the 'Otwarte konkursy' sidebar block.

    The sidebar HTML contains:
      <section ... id="otwarte-konkursy" ...> or a heading 'Otwarte konkursy'
      followed by <li> elements each with:
        <a href="/ogloszenia/konkursy/{slug}">{title}</a>
        ... <span>{DD MON}</span>  or plain text date
    """
    opps: list[dict] = []

    # Locate the sidebar section
    # Strategy 1: anchor id="otwarte-konkursy"
    idx = html_text.find('id="otwarte-konkursy"')
    if idx < 0:
        idx = html_text.find("otwarte-konkursy")
    if idx < 0:
        # Strategy 2: heading text
        idx = html_text.lower().find("otwarte konkursy")
    if idx < 0:
        print("  NCN WARNING: 'Otwarte konkursy' section not found on seed page.")
        return []

    # Take a generous window after the anchor
    block = html_text[idx: idx + 8000]

    # Extract all /ogloszenia/konkursy/ links in this block
    link_pat = re.compile(
        r'<a\s[^>]*href="/ogloszenia/konkursy/([^"?#\s]+)"[^>]*>(.*?)</a>',
        re.DOTALL | re.IGNORECASE,
    )

    seen_slugs: set[str] = set()
    for m in link_pat.finditer(block):
        slug       = m.group(1).strip().rstrip("/")
        inner_html = m.group(2)
        title      = _strip_tags(inner_html).strip()

        if not title or not slug:
            continue
        if slug in seen_slugs:
            continue
        seen_slugs.add(slug)

        # Look for a date in a small window after this link (within 400 chars)
        link_end = m.end()
        nearby   = block[link_end: link_end + 400]
        # Match "DD sty" / "31 lip" / "8 lip" etc.
        date_m   = re.search(
            r"(\d{1,2})\s+(" + "|".join(PL_MONTHS.keys()) + r")",
            nearby, re.IGNORECASE | re.UNICODE,
        )
        date_str    = date_m.group(0) if date_m else None
        deadline_iso = _parse_pl_sidebar_date(date_str) if date_str else None

        url = NCN_COMP_URL.format(slug=slug)
        opps.append({
            "title":        title,
            "slug":         slug,
            "url":          url,
            "deadline_iso": deadline_iso,
            "date_str":     date_str,
        })
        print(f"  NCN: found '{title}' → deadline {deadline_iso or date_str or 'unknown'}")

    return opps


def _fetch_competition_description(session: requests.Session, url: str) -> tuple[str | None, str | None]:
    """
    Fetch an individual competition page and extract:
    - A short English/Latin description snippet
    - A more precise deadline from body text (overrides sidebar date if found)

    Returns (description, deadline_iso_or_None).
    """
    page_html = _fetch_page(session, url)
    if not page_html:
        return None, None

    # Find main content area (after navigation)
    main_start = page_html.find('<main')
    if main_start < 0:
        main_start = page_html.find('id="main-content"')
    if main_start < 0:
        main_start = page_html.find('<article')
    if main_start < 0:
        main_start = 0

    main_html = page_html[main_start: main_start + 15000]
    main_text = _strip_tags(main_html)

    # Extract deadline from body text (Polish format)
    deadline_iso = _parse_pl_body_deadline(main_text)

    # Extract a description: first substantial paragraph after h1
    h1_m = re.search(r"<h1[^>]*>(.*?)</h1>", main_html, re.DOTALL | re.IGNORECASE)
    desc_start = h1_m.end() if h1_m else 0
    desc_html  = main_html[desc_start: desc_start + 5000]

    para_m = re.search(
        r"<p[^>]*>((?:(?!</p>).){50,})</p>",
        desc_html, re.DOTALL | re.IGNORECASE,
    )
    description = _strip_tags(para_m.group(1)).strip()[:500] if para_m else None

    return description, deadline_iso


def _fetch_ncn_calls(fetch_details: bool = True) -> list[dict]:
    session = requests.Session()
    session.headers.update({
        "Accept":          "text/html,application/xhtml+xml,*/*",
        "Accept-Language": "pl-PL,pl;q=0.9,en-US;q=0.5,en;q=0.3",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })

    print(f"  NCN: fetching seed page {NCN_SEED_URL}")
    seed_html = _fetch_page(session, NCN_SEED_URL)
    if not seed_html:
        # Fallback: try the harmonogram page in Polish
        print("  NCN: seed failed, trying fallback URL")
        seed_html = _fetch_page(session, "https://ncn.gov.pl/ogloszenia/konkursy")
    if not seed_html:
        print("  NCN ERROR: cannot fetch any seed page — aborting.")
        return []

    competitions = _parse_sidebar(seed_html)
    print(f"  NCN: {len(competitions)} open competitions found in sidebar.")

    if not fetch_details or not competitions:
        return competitions

    # Enrich with body-page descriptions and more precise deadlines
    for comp in competitions:
        time.sleep(0.5)  # polite crawl delay
        desc, deadline_body = _fetch_competition_description(session, comp["url"])
        if desc:
            comp["description"] = desc
        if deadline_body:
            # Only override sidebar deadline if body deadline is in the future
            try:
                if datetime.date.fromisoformat(deadline_body) >= datetime.date.today():
                    comp["deadline_iso"] = deadline_body
            except ValueError:
                pass
        print(
            f"  NCN detail: '{comp['title']}' — deadline={comp.get('deadline_iso')} "
            f"desc={'yes' if desc else 'no'}"
        )

    return competitions


def _map_call(comp: dict) -> dict | None:
    title = comp.get("title", "").strip()
    url   = comp.get("url", "").strip()
    if not title or not url:
        return None

    deadline_iso = comp.get("deadline_iso")
    today        = datetime.date.today()

    # Skip if deadline is already past
    if deadline_iso:
        try:
            if datetime.date.fromisoformat(deadline_iso) < today:
                return None
        except ValueError:
            pass

    thematic_sectors = _infer_sectors(
        (title or "") + " " + (comp.get("description") or "")
    )

    return {
        "grant_title":              title,
        "funder_name":              "NCN (National Science Centre Poland)",
        "source_url":               url,
        "application_portal_url":   "https://osf.opi.org.pl/",
        "description":              comp.get("description"),
        "application_deadline":     deadline_iso,
        "application_deadline_raw": comp.get("date_str"),
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "pl",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 "PLN",
        "thematic_sectors":         thematic_sectors,
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["PL"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_ncn",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{url}|{title}|{deadline_iso}".encode()
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
    parser = argparse.ArgumentParser(description="NCN Poland → GrantGlobe ingestor")
    parser.add_argument("--dry-run",       action="store_true")
    parser.add_argument("--no-details",    action="store_true",
                        help="Skip fetching individual competition pages (faster)")
    args = parser.parse_args()

    fetch_details = not args.no_details

    print("Fetching NCN Poland open competitions …")
    raw_comps = _fetch_ncn_calls(fetch_details=fetch_details)
    print(f"  {len(raw_comps)} raw competitions scraped.")

    mapped = []
    for c in raw_comps:
        g = _map_call(c)
        if g and g.get("source_url") and g.get("grant_title"):
            mapped.append(g)

    seen: set[str] = set()
    deduped = [g for g in mapped if not (g["source_url"] in seen or seen.add(g["source_url"]))]
    print(f"  {len(deduped)} competitions to upsert after filtering.")

    if args.dry_run:
        print("\n[DRY RUN] First 3 records:")
        for g in deduped[:3]:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
        return

    if not deduped:
        print("  Nothing to upsert.")
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
