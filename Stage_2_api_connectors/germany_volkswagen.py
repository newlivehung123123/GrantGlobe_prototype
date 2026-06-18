#!/usr/bin/env python3
"""
Volkswagen Foundation connector — Stage 2 API source.

Scrapes the full funding portfolio from volkswagenstiftung.de/en/our-funding-portfolio.
No API key required. Server-rendered Drupal 10 HTML.

Coverage: Germany (private foundation; funds research at German institutions,
international collaborations possible).

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/germany_volkswagen.py [--dry-run]
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

VWF_BASE     = "https://www.volkswagenstiftung.de"
VWF_LIST_URL = "https://www.volkswagenstiftung.de/en/our-funding-portfolio"
MAX_PAGES    = 5   # Currently 3 pages; allow headroom

DOMAIN_SECTOR_MAP: dict[str, list[str]] = {
    "health":              ["Health Sciences"],
    "medical":             ["Health Sciences"],
    "medicine":            ["Health Sciences"],
    "biomedicine":         ["Health Sciences"],
    "neuroscience":        ["Health Sciences", "Science & Technology"],
    "biology":             ["Science & Technology"],
    "biochemistry":        ["Science & Technology"],
    "biophysics":          ["Science & Technology"],
    "physics":             ["Science & Technology"],
    "mathematics":         ["Science & Technology"],
    "chemistry":           ["Science & Technology"],
    "computer":            ["Science & Technology", "Technology & Innovation"],
    "engineering":         ["Science & Technology", "Technology & Innovation"],
    "artificial intelligence": ["Science & Technology", "Technology & Innovation"],
    "data":                ["Science & Technology", "Technology & Innovation"],
    "quantum":             ["Science & Technology", "Technology & Innovation"],
    "technology":          ["Technology & Innovation"],
    "innovation":          ["Technology & Innovation"],
    "climate":             ["Climate & Environment"],
    "environment":         ["Climate & Environment"],
    "ecology":             ["Climate & Environment"],
    "circular":            ["Climate & Environment"],
    "biodiversity":        ["Climate & Environment"],
    "sustainability":      ["Climate & Environment"],
    "energy":              ["Climate & Environment", "Science & Technology"],
    "agriculture":         ["Agriculture & Food"],
    "forest":              ["Agriculture & Food", "Climate & Environment"],
    "social":              ["Social Sciences & Humanities"],
    "sociology":           ["Social Sciences & Humanities"],
    "humanities":          ["Social Sciences & Humanities"],
    "history":             ["Social Sciences & Humanities"],
    "philosophy":          ["Social Sciences & Humanities"],
    "literature":          ["Social Sciences & Humanities"],
    "culture":             ["Arts & Culture"],
    "art":                 ["Arts & Culture"],
    "music":               ["Arts & Culture"],
    "democracy":           ["Social Sciences & Humanities"],
    "political":           ["Social Sciences & Humanities"],
    "economics":           ["Social Sciences & Humanities"],
    "education":           ["Education & Training"],
    "research system":     ["Research & Innovation"],
    "open science":        ["Research & Innovation"],
    "wealth":              ["Social Sciences & Humanities"],
    "mobility":            ["Social Sciences & Humanities", "Science & Technology"],
    "global health":       ["Health Sciences"],
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
    date_str = re.sub(r",?\s*\d+:\d+.*", "", date_str).strip()
    for fmt in ("%d %B %Y", "%d %b %Y", "%Y-%m-%d", "%B %d, %Y", "%d/%m/%Y"):
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


def _fetch_page(session: requests.Session, url: str,
                params: dict | None = None) -> str | None:
    try:
        resp = session.get(url, params=params, timeout=30)
        if resp.status_code == 404:
            return None
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

# h3 headings: grant titles in the listing
_H3_PAT = re.compile(r"<h3[^>]*>(.*?)</h3>", re.DOTALL | re.IGNORECASE)

# "Learn more" link to individual funding-offer pages (VWF-hosted only)
_LEARN_MORE_PAT = re.compile(
    r'href="(/en/funding/funding-offer/[^"?#]+)"',
    re.IGNORECASE,
)

# Deadline pattern: "27 August 2026 Deadline" or "18 November 2026 Deadline Short Proposals"
_DEADLINE_PAT = re.compile(
    r"(\d{1,2}\s+"
    r"(?:Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|"
    r"Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    r"\s+\d{4})\s*Deadline",
    re.IGNORECASE,
)

# Section boundary: stop parsing at "Completed" section
_COMPLETED_PAT = re.compile(r"##\s*Completed|class=[\"'][^\"']*completed[\"']", re.IGNORECASE)


def _parse_grants_from_html(html_text: str, today: datetime.date) -> list[dict]:
    """
    Extract funding opportunities from a VWF listing page.

    Page structure per card (Drupal 10 Twig template):
      <div class="date-text">DD Month YYYY Deadline</div>   ← status/date
      <h3 class="card__title">Grant Title</h3>              ← title
      <p class="card__description">Description</p>          ← description
      <a href="/en/funding/funding-offer/{slug}">Learn more</a>  ← link

    Strategy:
      1. Find all h3 headings inside the "Funding portfolio" content section.
      2. For each h3, look forward for a VWF "funding-offer" href.
      3. Look backward from the h3 for deadline / status text.
      4. Filter out "No open call" grants without future deadlines.
    """
    opps: list[dict] = []
    seen_urls: set[str] = set()

    # Only process the content between "Funding portfolio" heading and "Completed"
    start_marker = "Funding portfolio"
    start_idx = html_text.find(start_marker)
    if start_idx == -1:
        start_idx = 0

    end_m = _COMPLETED_PAT.search(html_text, start_idx)
    end_idx = end_m.start() if end_m else len(html_text)

    content = html_text[start_idx:end_idx]

    for m in _H3_PAT.finditer(content):
        title_raw = _strip_tags(m.group(1)).strip()
        if not title_raw or len(title_raw) < 8:
            continue

        # Skip section headings (profile areas) that appear as h3
        if any(skip in title_raw.lower() for skip in [
            "societal transformations", "exploration", "understanding research",
            "zukunft.niedersachsen", "funding portfolio", "learn more",
        ]):
            continue

        h3_pos = m.start()

        # --- Forward scan: find the VWF funding-offer link within 3000 chars ---
        post_block = content[m.end(): m.end() + 3000]
        href_m = _LEARN_MORE_PAT.search(post_block)
        if not href_m:
            # No VWF-hosted page for this grant (e.g. external zukunft.niedersachsen link)
            continue

        href = href_m.group(1).strip()
        url = f"{VWF_BASE}{href}"
        if url in seen_urls:
            continue
        seen_urls.add(url)

        # --- Backward scan: find date and status text within 1200 chars before h3 ---
        pre_block = content[max(0, h3_pos - 1200): h3_pos]
        pre_lower = pre_block.lower()

        # Determine grant status
        no_open = "no open call" in pre_lower or "no further call" in pre_lower
        rolling = (
            "apply anytime" in pre_lower
            or "applications can be submitted at any time" in pre_lower
            or "application at any time" in pre_lower
        )
        vague_upcoming = any(kw in pre_lower for kw in [
            "expected", "presumably", "to be published", "currently being evaluated",
            "autumn 2026", "summer 2026", "winter 2026", "early 2027",
            "beginning of 2027",
        ])

        # Extract explicit deadline date
        dl_m = _DEADLINE_PAT.search(pre_block)
        deadline_raw = dl_m.group(1).strip() if dl_m else None
        deadline_iso = _parse_date(deadline_raw)

        # Classify status
        if rolling:
            status = "Rolling"
        elif no_open:
            # Could still be upcoming if a future deadline was mentioned
            if deadline_iso:
                try:
                    if datetime.date.fromisoformat(deadline_iso) >= today:
                        status = "Open"
                    else:
                        # Past deadline + no open call → skip
                        continue
                except ValueError:
                    continue
            elif vague_upcoming:
                status = "Upcoming"
            else:
                continue  # Truly closed, skip
        elif deadline_iso:
            try:
                if datetime.date.fromisoformat(deadline_iso) < today:
                    # Past deadline — still include as the grant may be rolling
                    # but mark as Upcoming (next cycle)
                    status = "Upcoming"
                    deadline_iso = None
                    deadline_raw = None
                else:
                    status = "Open"
            except ValueError:
                status = "Open"
        elif vague_upcoming:
            status = "Upcoming"
        else:
            status = "Upcoming"

        # --- Description: first <p> in the 1500 chars after h3 ---
        desc_m = re.search(r"<p[^>]*>(.*?)</p>", post_block[:1500], re.DOTALL | re.IGNORECASE)
        description = _strip_tags(desc_m.group(1)).strip()[:400] if desc_m else None

        # Slug for opp_id
        slug = re.search(r"/funding-offer/([^/?#]+)/?$", href)
        opp_id = slug.group(1) if slug else href

        opps.append({
            "title":        title_raw,
            "url":          url,
            "opp_id":       opp_id,
            "deadline_iso": deadline_iso,
            "deadline_raw": deadline_raw,
            "description":  description,
            "status":       status,
        })

    return opps


def _fetch_vwf_opportunities() -> list[dict]:
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

    today = datetime.date.today()
    all_opps: list[dict] = []

    for page_num in range(0, MAX_PAGES):
        params: dict = {}
        if page_num > 0:
            params["page"] = page_num

        html_text = _fetch_page(session, VWF_LIST_URL, params=params)
        if not html_text:
            print(f"  VWF: page {page_num} returned no content — stopping.")
            break

        if page_num == 0:
            idx = html_text.find("/en/funding/funding-offer/")
            if idx > 0:
                print(f"  VWF: first funding-offer link at char {idx} ✓")
            else:
                print(f"  VWF WARNING: no funding-offer links on page 0")
                print(f"  VWF page 0 length: {len(html_text)} chars")

        page_opps = _parse_grants_from_html(html_text, today)

        if not page_opps:
            print(f"  VWF: page {page_num} yielded 0 opportunities — stopping.")
            break

        existing_urls = {o["url"] for o in all_opps}
        new_opps = [o for o in page_opps if o["url"] not in existing_urls]
        all_opps.extend(new_opps)
        print(f"  VWF page {page_num}: {len(new_opps)} new opportunities "
              f"(total: {len(all_opps)})")

        # Pagination: Drupal uses ?page=0,1,2; stop when we see no "next page" link
        if f"page={page_num + 1}" not in html_text and f"page%3D{page_num + 1}" not in html_text:
            break

        time.sleep(0.5)

    return all_opps


# ---------------------------------------------------------------------------
# Mapping
# ---------------------------------------------------------------------------

def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url   = opp.get("url", "").strip()
    if not title or not url:
        return None

    status = opp.get("status", "Open")

    return {
        "grant_title":              title,
        "funder_name":              "Volkswagen Foundation",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              opp.get("description"),
        "application_deadline":     opp.get("deadline_iso"),
        "application_deadline_raw": opp.get("deadline_raw"),
        "grant_opening_date":       None,
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         _infer_sectors(
            (title or "") + " " + (opp.get("description") or "")
        ),
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe", "Global"],
        "applicant_base_countries": ["DE"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   ["Postdoctoral Researcher", "Professor"],
        "domain":                   "api_volkswagen_foundation",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{opp.get('opp_id') or url}|{title}|{opp.get('deadline_iso')}".encode()
        ).hexdigest(),
    }


# ---------------------------------------------------------------------------
# DB operations
# ---------------------------------------------------------------------------

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
    parser = argparse.ArgumentParser(description="Volkswagen Foundation → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching Volkswagen Foundation funding portfolio …")
    raw_opps = _fetch_vwf_opportunities()
    print(f"  {len(raw_opps)} raw records scraped.")

    mapped = [_map_opportunity(o) for o in raw_opps]
    mapped = [g for g in mapped if g and g.get("source_url") and g.get("grant_title")]

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
