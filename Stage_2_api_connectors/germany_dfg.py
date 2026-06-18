#!/usr/bin/env python3
"""
DFG (German Research Foundation) connector — Stage 2 API source.

Scrapes open calls from DFG's "Information for Researchers" RSS feed.
No API key required. RSS 2.0 feed, server-side generated.

Feed: https://www.dfg.de/service/rss/de/323556/feed.rss
      "Calls for DFG funding programmes and funding-related news"

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/germany_dfg.py [--dry-run]
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
import xml.etree.ElementTree as ET

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

DFG_RSS_URL     = "https://www.dfg.de/service/rss/de/323556/feed.rss"
DFG_BASE        = "https://www.dfg.de"

# The DFG IFR feed is curated for researchers — most items are relevant.
# We exclude obvious non-calls rather than trying to keyword-match calls.
import re as _re
_EXCLUDE_PATTERNS = [
    _re.compile(p, _re.IGNORECASE | _re.UNICODE)
    for p in [
        r"kongresse?\s+und\s+tagungen",   # conference listings
        r"tagungsank",                     # conference announcements
        r"fotowettbewerb",                 # photo contests
        r"fachkollegienwahl",              # committee elections
        r"f[äa]cherstruktur",              # election field structure
        r"wahlstellen",                    # polling places
        r"kalender\s+\d{4}.*wettbewerb",  # calendar/competition
        r"jahresbericht",                  # annual report
        r"\bjubil[äa]um\b",               # anniversary (pure news)
    ]
]

TOPIC_SECTOR_MAP: dict[str, list[str]] = {
    "life science":    ["Health Sciences"],
    "health":          ["Health Sciences"],
    "medicine":        ["Health Sciences"],
    "biology":         ["Health Sciences", "Science & Technology"],
    "chemistry":       ["Science & Technology"],
    "physics":         ["Science & Technology"],
    "mathematics":     ["Science & Technology"],
    "engineering":     ["Science & Technology", "Technology & Innovation"],
    "computer":        ["Science & Technology", "Information & Communication Technologies"],
    "digital":         ["Science & Technology", "Information & Communication Technologies"],
    "artificial intelligence": ["Science & Technology", "Information & Communication Technologies"],
    "ai":              ["Science & Technology", "Information & Communication Technologies"],
    "climate":         ["Climate & Environment"],
    "environment":     ["Climate & Environment"],
    "energy":          ["Climate & Environment", "Science & Technology"],
    "social":          ["Social Sciences & Humanities"],
    "humanities":      ["Social Sciences & Humanities"],
    "history":         ["Social Sciences & Humanities"],
    "economics":       ["Social Sciences & Humanities"],
    "education":       ["Education & Training"],
    "innovation":      ["Technology & Innovation"],
}

# RFC 2822 month names used in RSS <pubDate>
_RSS_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4,
    "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "oct": 10, "nov": 11, "dec": 12,
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


def _parse_rss_date(date_str: str | None) -> str | None:
    """Parse RFC 2822 date from RSS <pubDate> → ISO 8601 string."""
    if not date_str:
        return None
    # Typical: "Mon, 15 Apr 2024 10:00:00 +0000"
    m = re.search(
        r"(\d{1,2})\s+([A-Za-z]{3})\s+(\d{4})",
        date_str.strip(),
    )
    if not m:
        return None
    day   = int(m.group(1))
    month = _RSS_MONTHS.get(m.group(2).lower())
    year  = int(m.group(3))
    if not month:
        return None
    try:
        return datetime.date(year, month, day).isoformat()
    except ValueError:
        return None


def _extract_deadline_from_text(text: str) -> str | None:
    """
    Try to pull a deadline date from the item description/title.

    DFG IFR articles mention deadlines like:
      "Deadline: 15 April 2025"
      "submission deadline: 30 June 2026"
      "closing date: 1 March 2026"
    """
    # ISO date yyyy-mm-dd
    m = re.search(r"\b(202\d)-(0[1-9]|1[0-2])-([0-2]\d|3[01])\b", text)
    if m:
        try:
            return datetime.date(
                int(m.group(1)), int(m.group(2)), int(m.group(3))
            ).isoformat()
        except ValueError:
            pass

    # "15 April 2026" or "April 15, 2026"
    months_long = {
        "january": 1, "february": 2, "march": 3, "april": 4,
        "may": 5, "june": 6, "july": 7, "august": 8,
        "september": 9, "october": 10, "november": 11, "december": 12,
    }
    m = re.search(
        r"\b(\d{1,2})\s+(" + "|".join(months_long) + r")\s+(202\d)\b",
        text, re.IGNORECASE,
    )
    if m:
        month_num = months_long.get(m.group(2).lower())
        if month_num:
            try:
                return datetime.date(int(m.group(3)), month_num, int(m.group(1))).isoformat()
            except ValueError:
                pass
    m = re.search(
        r"\b(" + "|".join(months_long) + r")\s+(\d{1,2}),?\s+(202\d)\b",
        text, re.IGNORECASE,
    )
    if m:
        month_num = months_long.get(m.group(1).lower())
        if month_num:
            try:
                return datetime.date(int(m.group(3)), month_num, int(m.group(2))).isoformat()
            except ValueError:
                pass

    # "30.06.2026" or "30/06/2026"
    m = re.search(r"\b(\d{2})[./](\d{2})[./](202\d)\b", text)
    if m:
        try:
            return datetime.date(int(m.group(3)), int(m.group(2)), int(m.group(1))).isoformat()
        except ValueError:
            pass

    return None


def _is_relevant(title: str, description: str) -> bool:
    """
    Return True unless the item matches a known non-call pattern.
    The DFG IFR feed is researcher-facing, so we accept by default
    and only exclude obvious non-call content types.
    """
    combined = title + " " + description
    return not any(pat.search(combined) for pat in _EXCLUDE_PATTERNS)


def _infer_sectors(text: str) -> list[str]:
    text_lower = text.lower()
    sectors: list[str] = []
    for keyword, sector_list in TOPIC_SECTOR_MAP.items():
        if keyword in text_lower:
            sectors.extend(s for s in sector_list if s not in sectors)
    return sectors or ["Research & Innovation"]


def _fetch_rss(session: requests.Session) -> str | None:
    """Fetch the DFG RSS feed XML."""
    try:
        resp = session.get(DFG_RSS_URL, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: DFG RSS fetch failed: {e}")
        return None


def _parse_rss_items(xml_text: str) -> list[dict]:
    """
    Parse RSS 2.0 items from XML.

    Returns list of dicts with: title, link, description, pub_date.
    Falls back to simple regex parsing if ElementTree fails.
    """
    items: list[dict] = []

    # --- ElementTree parse ---
    try:
        # Strip any BOM
        xml_clean = xml_text.lstrip("﻿")
        root = ET.fromstring(xml_clean)

        # RSS 2.0: root → channel → item
        ns: dict[str, str] = {}
        channel = root.find("channel")
        if channel is None:
            channel = root  # some feeds omit <channel>

        for item_el in channel.findall("item"):
            def _text(tag: str) -> str:
                el = item_el.find(tag)
                return (el.text or "").strip() if el is not None else ""

            items.append({
                "title":       _text("title"),
                "link":        _text("link"),
                "description": _strip_tags(_text("description")),
                "pub_date":    _text("pubDate"),
            })

        if items:
            print(f"  DFG: parsed {len(items)} RSS items via ElementTree")
            return items

    except ET.ParseError as e:
        print(f"  DFG WARNING: ElementTree parse failed ({e}), trying regex fallback")

    # --- Regex fallback ---
    for m in re.finditer(r"<item>(.*?)</item>", xml_text, re.DOTALL):
        block = m.group(1)

        def _tag(tag: str) -> str:
            t = re.search(rf"<{tag}[^>]*>(?:<!\[CDATA\[)?(.*?)(?:]]>)?</{tag}>",
                          block, re.DOTALL)
            return _strip_tags(t.group(1)).strip() if t else ""

        items.append({
            "title":       _tag("title"),
            "link":        _tag("link"),
            "description": _tag("description"),
            "pub_date":    _tag("pubDate"),
        })

    print(f"  DFG: parsed {len(items)} RSS items via regex fallback")
    return items


def _fetch_dfg_calls() -> list[dict]:
    session = requests.Session()
    session.headers.update({
        "Accept":          "application/rss+xml, application/xml, text/xml, */*",
        "Accept-Encoding": "gzip, deflate",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })

    xml_text = _fetch_rss(session)
    if not xml_text:
        print("  DFG: no RSS content — aborting.")
        return []

    print(f"  DFG RSS: {len(xml_text)} chars received")

    raw_items = _parse_rss_items(xml_text)
    today = datetime.date.today()

    calls: list[dict] = []
    for item in raw_items:
        title       = item.get("title", "").strip()
        link        = item.get("link", "").strip()
        description = item.get("description", "").strip()
        pub_date    = item.get("pub_date", "")

        if not title or not link:
            continue

        # Accept all items except known non-call content types.
        if not _is_relevant(title, description):
            print(f"  DFG skip (excluded): {title[:80]}")
            continue

        # Parse dates
        pub_date_iso = _parse_rss_date(pub_date)
        deadline_iso = _extract_deadline_from_text(title + " " + description)

        # Skip if deadline is already past
        if deadline_iso:
            try:
                if datetime.date.fromisoformat(deadline_iso) < today:
                    continue
            except ValueError:
                pass

        # Skip very old pub dates (> 2 years) with no future deadline
        if pub_date_iso and not deadline_iso:
            try:
                pub = datetime.date.fromisoformat(pub_date_iso)
                if pub.year < today.year - 1:
                    continue
            except ValueError:
                pass

        calls.append({
            "title":       title,
            "url":         link,
            "description": description[:500] if description else None,
            "deadline_iso": deadline_iso,
            "pub_date_iso": pub_date_iso,
        })

    return calls


def _map_call(item: dict) -> dict | None:
    title = item.get("title", "").strip()
    url   = item.get("url", "").strip()
    if not title or not url:
        return None

    deadline_iso = item.get("deadline_iso")
    pub_date_iso = item.get("pub_date_iso")

    thematic_sectors = _infer_sectors(
        (title or "") + " " + (item.get("description") or "")
    )

    return {
        "grant_title":              title,
        "funder_name":              "DFG (German Research Foundation)",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              item.get("description"),
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_iso,
        "grant_opening_date":       pub_date_iso,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         thematic_sectors,
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["DE"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_dfg",
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
    parser = argparse.ArgumentParser(description="DFG → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching DFG IFR RSS feed …")
    raw_calls = _fetch_dfg_calls()
    print(f"  {len(raw_calls)} relevant calls found after filtering.")

    today = datetime.date.today()
    mapped = []
    for item in raw_calls:
        g = _map_call(item)
        if not g or not g.get("source_url") or not g.get("grant_title"):
            continue
        mapped.append(g)

    seen: set[str] = set()
    deduped = [g for g in mapped if not (g["source_url"] in seen or seen.add(g["source_url"]))]
    print(f"  {len(deduped)} calls to upsert after deduplication.")

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
