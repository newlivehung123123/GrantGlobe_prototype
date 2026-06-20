#!/usr/bin/env python3
"""
Gates Foundation — Grand Challenges connector.

The Grand Challenges initiative (gcgh.grandchallenges.org) is the Gates Foundation's
primary competitive open-call funding platform for innovations in global health and
development. It issues rolling calls throughout the year targeting specific technical
problems; calls from partner initiatives (Grand Challenges Africa, Grand Challenges
India, Grand Challenges South Africa, Grand Challenges Canada, etc.) also appear on
the platform.

This connector fetches the live listing of open challenges, scrapes each challenge
page for its deadline and metadata, and writes a record per open challenge. On each
run it also marks any previously inserted "Open" records that are no longer on the
listing page as "Closed".

Live fetching:
  - Listing page (server-rendered Next.js):
      https://gcgh.grandchallenges.org/grant-opportunities
    Contains href links to each open challenge's detail page.
  - Challenge detail pages:
      https://gcgh.grandchallenges.org/challenge/<slug>
    Deadline and initiative are embedded as static text in the sidebar, e.g.
        "Initiative Grand Challenges South Africa"
        "Date Open May 12, 2026, 6:00 am PDT"
        "Deadline Jun 23, 2026, 3:00 pm PDT"

Country mapping:
  Initiative names contain a region/country qualifier. The connector maps known
  sub-national initiatives to ISO-3166-1 alpha-2 codes. Challenges labelled only
  "Grand Challenges" (the global initiative) are treated as open globally.

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/gates_grand_challenges.py [--dry-run] [--skip-fetch]
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

FUNDER  = "Gates Foundation (Grand Challenges)"
DOMAIN  = "api_grand_challenges"

LISTING_URL = "https://gcgh.grandchallenges.org/grant-opportunities"
BASE_URL    = "https://gcgh.grandchallenges.org"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9",
}

# Map substrings of initiative name → ISO-3166-1 alpha-2 codes.
# Order matters: more specific entries should come first.
INITIATIVE_COUNTRIES: list[tuple[str, list[str]]] = [
    ("south africa",    ["ZA"]),
    ("india",           ["IN"]),
    ("canada",          ["CA"]),
    ("brazil",          ["BR"]),
    ("china",           ["CN"]),
    ("ethiopia",        ["ET"]),
    ("kenya",           ["KE"]),
    ("nigeria",         ["NG"]),
    ("ghana",           ["GH"]),
    ("senegal",         ["SN"]),
    # "Grand Challenges Africa" spans many countries — treat as regional
    ("africa",          []),      # → applicant_base_regions: ["Sub-Saharan Africa"]
]

AFRICA_REGIONS = ["Sub-Saharan Africa"]


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
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html, flags=re.DOTALL)
    html = re.sub(r'<[^>]+>', ' ', html)
    html = html.replace('&nbsp;', ' ').replace('&amp;', '&')
    html = html.replace('&lt;', '<').replace('&gt;', '>').replace('&quot;', '"')
    return re.sub(r'\s+', ' ', html).strip()


def _content_hash(*parts: str) -> str:
    return hashlib.sha256("|".join(str(p) for p in parts).encode()).hexdigest()


def _parse_date(raw: str) -> datetime.date | None:
    """Parse 'Jun 23, 2026' or 'June 23, 2026' style date strings."""
    raw = raw.strip()
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _initiative_geo(initiative: str) -> tuple[list[str], list[str], list[str], list[str]]:
    """
    Returns (base_countries, focus_countries, base_regions, focus_regions)
    based on the initiative name.
    """
    lower = initiative.lower()
    for keyword, countries in INITIATIVE_COUNTRIES:
        if keyword in lower:
            if keyword == "africa":
                return [], [], AFRICA_REGIONS, AFRICA_REGIONS
            return countries, countries, [], []
    # Default: global
    return [], [], ["Global"], ["Global"]


# ---------------------------------------------------------------------------
# Listing page parser
# ---------------------------------------------------------------------------

def _parse_listing(html: str) -> list[str]:
    """
    Extract unique challenge URLs from the grant-opportunities page.
    Handles both relative (/challenge/...) and absolute URLs.
    """
    urls: list[str] = []
    seen: set[str] = set()
    for m in re.finditer(
        r'href="(/challenge/[^"]+|https://gcgh\.grandchallenges\.org/challenge/[^"]+)"',
        html,
    ):
        href = m.group(1)
        url = href if href.startswith("http") else BASE_URL + href
        if url not in seen:
            seen.add(url)
            urls.append(url)
    return urls


# ---------------------------------------------------------------------------
# Challenge detail page parser
# ---------------------------------------------------------------------------

def _parse_challenge(page_html: str, url: str, today: datetime.date) -> dict | None:
    """
    Parse a challenge detail page into a DB record dict.
    Returns None if the page has no parseable deadline or is already closed.
    """
    text = _strip_tags(page_html)

    # ── Title ────────────────────────────────────────────────────────────────
    # Prefer the full <h1> over truncated og:title
    h1_m = re.search(r'<h1[^>]*>(.*?)</h1>', page_html, re.DOTALL | re.IGNORECASE)
    if h1_m:
        title = html.unescape(_strip_tags(h1_m.group(0)).strip())
    else:
        og_m = re.search(r'<meta\s+property="og:title"\s+content="([^"]+)"', page_html)
        title = html.unescape(og_m.group(1).strip()) if og_m else ""
    if not title:
        return None

    # ── Deadline ─────────────────────────────────────────────────────────────
    # Sidebar text: "Deadline Jun 23, 2026, 3:00 pm PDT"
    dl_m = re.search(r'\bDeadline\s+([A-Za-z]+ \d{1,2},\s+\d{4})', text)
    if not dl_m:
        return None
    deadline = _parse_date(dl_m.group(1))
    if deadline is None or deadline < today:
        return None  # Already closed

    # ── Initiative ───────────────────────────────────────────────────────────
    # Sidebar text: "Initiative Grand Challenges South Africa Challenge Topic ..."
    init_m = re.search(
        r'\bInitiative\s+(Grand Challenges[^|]+?)(?:\s+Challenge Topic|\s+Date Open|\s+Deadline)',
        text,
    )
    initiative = init_m.group(1).strip() if init_m else "Grand Challenges"

    # ── Date Open ────────────────────────────────────────────────────────────
    open_m = re.search(r'\bDate Open\s+([A-Za-z]+ \d{1,2},\s+\d{4})', text)
    open_date = _parse_date(open_m.group(1)) if open_m else None

    # ── Description ──────────────────────────────────────────────────────────
    # Use meta description as base; supplement with body intro
    meta_m = re.search(r'<meta\s+name="description"\s+content="([^"]+)"', page_html)
    meta_desc = meta_m.group(1).strip() if meta_m else ""

    # Extract body intro: find text after the title and take the first paragraph
    title_pos = text.find(title)
    body_intro = ""
    if title_pos > -1:
        after = text[title_pos + len(title):].strip()
        # Skip image alt text (typically short, all-caps or path-like)
        body_intro = after[:900].strip()

    desc = body_intro if len(body_intro) > len(meta_desc) else meta_desc
    if not desc:
        desc = title

    # ── Geography ────────────────────────────────────────────────────────────
    base_countries, focus_countries, base_regions, focus_regions = _initiative_geo(
        initiative
    )

    # ── Status ───────────────────────────────────────────────────────────────
    days_until = (deadline - today).days
    status = "Open"  # Only open challenges appear on the listing page

    return {
        "grant_title":              title,
        "funder_name":              FUNDER,
        "source_url":               url,
        "application_portal_url":   url,
        "description":              desc,
        "application_deadline":     deadline.isoformat(),
        "application_deadline_raw": f"{deadline.day} {deadline.strftime('%B %Y')}",
        "grant_opening_date":       open_date.isoformat() if open_date else None,
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         [
            "Global Health", "Global Development", "Research & Innovation",
            "Life Sciences",
        ],
        "grant_types":              ["Research Grant", "Innovation Grant"],
        "applicant_base_regions":   base_regions,
        "geographic_focus_regions": focus_regions,
        "applicant_base_countries": base_countries,
        "geographic_focus_countries": focus_countries,
        "organisation_types":       [
            "University", "Research Institution",
            "Non-Profit Organisation", "For-Profit Company",
        ],
        "individual_eligibility":   [
            "Faculty Researcher", "Early Career Researcher", "Innovator",
        ],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             _content_hash(url, title, deadline.isoformat()),
        # Internal carry-alongs (stripped before DB insert)
        "_days_until":              days_until,
        "_initiative":              initiative,
    }


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

def _upsert(conn, record: dict) -> str:
    """Insert or update by source_url. Returns 'inserted' or 'updated'."""
    db_rec = {k: v for k, v in record.items() if not k.startswith("_")}

    cur = conn.cursor()
    cur.execute(
        "SELECT id FROM grants WHERE source_url = %s", (db_rec["source_url"],)
    )
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


def _close_stale(conn, active_urls: set[str], dry_run: bool) -> int:
    """
    Mark any 'Open' records with domain=DOMAIN whose source_url is NOT in
    active_urls as 'Closed'. Returns number of records closed.
    """
    cur = conn.cursor()
    cur.execute(
        "SELECT id, source_url, grant_title FROM grants "
        "WHERE domain = %s AND current_status = 'Open'",
        (DOMAIN,),
    )
    rows = cur.fetchall()
    closed = 0
    for row_id, src_url, grant_title in rows:
        if src_url not in active_urls:
            if dry_run:
                print(f"  [DRY RUN] Would close: {grant_title[:60]}")
            else:
                cur.execute(
                    "UPDATE grants SET current_status = 'Closed', crawl_date = %s "
                    "WHERE id = %s",
                    (datetime.date.today().isoformat(), row_id),
                )
            closed += 1
    return closed


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Gates Foundation Grand Challenges connector"
    )
    parser.add_argument("--dry-run",     action="store_true",
                        help="Print records without writing to DB")
    parser.add_argument("--skip-fetch",  action="store_true",
                        help="Skip live page fetch (for testing)")
    args = parser.parse_args()

    today = datetime.date.today()
    records: list[dict] = []
    active_urls: set[str] = set()

    if args.skip_fetch:
        print("  [SKIP-FETCH] No live page fetched.")
    else:
        # Step 1: fetch listing page
        print(f"  Fetching listing: {LISTING_URL}")
        listing_html = _fetch(LISTING_URL)
        if not listing_html:
            print("  ERROR: Could not fetch listing page.")
            sys.exit(1)

        challenge_urls = _parse_listing(listing_html)
        print(f"  Found {len(challenge_urls)} open challenge(s) on listing page.")

        # Step 2: fetch each challenge detail page
        for url in challenge_urls:
            print(f"  Fetching: {url}")
            html = _fetch(url)
            if not html:
                continue
            rec = _parse_challenge(html, url, today)
            if rec is None:
                print(f"    SKIP: could not parse deadline or already closed.")
                continue
            records.append(rec)
            active_urls.add(url)
            print(
                f"    [{rec['current_status']:<6}] {rec['grant_title'][:55]}  "
                f"→ {rec['application_deadline']}  ({rec['_days_until']}d) "
                f"[{rec['_initiative']}]"
            )
            time.sleep(1)

    # ── Print summary ──────────────────────────────────────────────────────
    print(f"\n{'─'*65}")
    print(f"  Grand Challenges — {len(records)} open challenge(s)  (today: {today})")
    print(f"{'─'*65}")
    for rec in records:
        print(
            f"  [{rec['current_status']:<6}] {rec['grant_title']:<50} "
            f"→ {rec['application_deadline']}  ({rec['_days_until']}d)"
        )

    if args.dry_run:
        print("\n[DRY RUN] Full records:")
        for rec in records:
            display = {k: v for k, v in rec.items() if not k.startswith("_")}
            print(json.dumps(display, indent=2, default=str))
        # Also show what would be closed
        if not args.skip_fetch:
            conn = _connect()
            closed = _close_stale(conn, active_urls, dry_run=True)
            conn.close()
            print(f"\n  [DRY RUN] Would close {closed} stale Open record(s).")
        return

    # ── Write to DB ────────────────────────────────────────────────────────
    conn = _connect()
    inserted = updated = err = closed = 0
    try:
        # Close stale records first
        closed = _close_stale(conn, active_urls, dry_run=False)
        if closed:
            conn.commit()
            print(f"  Closed {closed} stale record(s).")

        # Upsert active records
        for record in records:
            try:
                result = _upsert(conn, record)
                conn.commit()
                print(f"  {result:9}  {record['grant_title'][:60]}")
                if result == "inserted":
                    inserted += 1
                else:
                    updated += 1
            except Exception as e:
                conn.rollback()
                print(f"  ERROR [{record['grant_title'][:50]}]: {e}", file=sys.stderr)
                err += 1
    finally:
        conn.close()

    print(
        f"\n  Grand Challenges: {inserted} inserted, {updated} updated, "
        f"{closed} closed, {err} errors."
    )


if __name__ == "__main__":
    main()
