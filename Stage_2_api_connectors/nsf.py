#!/usr/bin/env python3
"""
NSF funding opportunities connector — Stage 2 API source.

Fetches NSF's OPEN funding opportunities (program solicitations and
announcements that are currently accepting proposals) from NSF's public RSS
feeds. No API key required.

    • Upcoming Due Dates       https://www.nsf.gov/rss/rss_www_funding_upcoming.xml
    • Program Announcements    https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml

Both feeds list opportunities that are open for application, so records are
ingested with current_status="Open". Each item links to a human-readable
nsf.gov/funding/opportunities/ page. NSF does not publish a machine-readable
feed of not-yet-open ("forthcoming") calls; those reach GrantGlobe via
grants.gov (forecasted → Forthcoming) instead.

History: this connector previously pulled the NSF *Awards* API, which returns
grants already disbursed to named researchers — not open calls. Those records
were reclassified Closed; this version replaces that source entirely.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/nsf.py [--dry-run]
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
import xml.etree.ElementTree as ET

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

NSF_FEEDS = [
    "https://www.nsf.gov/rss/rss_www_funding_upcoming.xml",
    "https://www.nsf.gov/rss/rss_www_funding_pgm_annc_inf.xml",
]

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "application/rss+xml, application/xml, text/xml",
}

# Deadline labels NSF uses in feed descriptions, in priority order (the main
# full-proposal deadline wins over target dates and letters of intent).
_DEADLINE_LABELS = [
    "Full Proposal Deadline Date",
    "Full Proposal Target Date",
    "Proposal Deadline Date",
    "Preliminary Proposal Deadline Date",
    "Application Deadline Date",
    "Letter of Intent Deadline Date",
]

# Keyword → thematic-sector inference (NSF feeds don't carry a directorate code).
_SECTOR_KEYWORDS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\b(artificial intelligence|machine learning|\bAI\b)", re.I),
        ["Information & Communication Technologies", "Science & Technology"]),
    (re.compile(r"\b(cyber|comput|software|data science|quantum|algorithm)", re.I),
        ["Information & Communication Technologies"]),
    (re.compile(r"\b(climate|environment|ocean|arctic|geoscience|earth|sustainab|polar)", re.I),
        ["Climate & Environment"]),
    (re.compile(r"\b(bio|genom|ecolog|life science|organism|microb)", re.I),
        ["Agriculture & Food", "Science & Technology"]),
    (re.compile(r"\b(health|medical|biomed|disease|clinical|neuro)", re.I),
        ["Health Sciences"]),
    (re.compile(r"\b(education|STEM|undergraduate|graduate|teacher|learning|curricul)", re.I),
        ["Education & Training"]),
    (re.compile(r"\b(physics|chemistry|math|materials|astronom|nano)", re.I),
        ["Science & Technology"]),
    (re.compile(r"\b(social|economic|behavioral|psycholog|sociolog|human)", re.I),
        ["Social Sciences & Humanities"]),
    (re.compile(r"\b(small business|SBIR|STTR|innovation|technology transfer|entrepreneur|commerciali)", re.I),
        ["Technology & Innovation"]),
    (re.compile(r"\b(engineer)", re.I), ["Science & Technology"]),
]

_AI_PATTERN = re.compile(r"\b(artificial intelligence|machine learning|\bAI\b|deep learning)", re.I)


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
    if not date_str:
        return None
    date_str = str(date_str).strip()
    if "T" in date_str:
        date_str = date_str.split("T")[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y", "%B %d, %Y", "%b %d, %Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _clean(text: str | None) -> str:
    """Strip HTML tags and unescape entities from a feed description."""
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _extract_deadlines(desc: str) -> tuple[str | None, str | None, str | None]:
    """Return (main_deadline_iso, main_deadline_raw, loi_deadline_iso) parsed
    from a feed description, preferring the full-proposal deadline."""
    date_re = r"([A-Z][a-z]+ \d{1,2},\s*\d{4})"
    main_iso = main_raw = loi_iso = None
    for label in _DEADLINE_LABELS:
        m = re.search(re.escape(label) + r"\s*:?\s*" + date_re, desc)
        if not m:
            continue
        iso = _parse_date(m.group(1))
        if label == "Letter of Intent Deadline Date":
            loi_iso = iso
            if main_iso is None:          # only fall back to LOI if nothing better
                main_iso, main_raw = iso, f"{label}: {m.group(1)}"
        elif main_iso is None or label.startswith("Full Proposal Deadline"):
            main_iso, main_raw = iso, f"{label}: {m.group(1)}"
    return main_iso, main_raw, loi_iso


def _infer_sectors(text: str) -> list[str]:
    sectors: list[str] = []
    for pat, secs in _SECTOR_KEYWORDS:
        if pat.search(text):
            for s in secs:
                if s not in sectors:
                    sectors.append(s)
    return sectors or ["Research & Innovation", "Science & Technology"]


# ---------------------------------------------------------------------------
# Fetch + map
# ---------------------------------------------------------------------------

def _fetch_opportunities() -> list[dict]:
    """Fetch and parse NSF open-opportunity items from the RSS feeds."""
    session = requests.Session()
    session.headers.update(_HEADERS)
    items: list[dict] = []
    for url in NSF_FEEDS:
        try:
            resp = session.get(url, timeout=30)
            resp.raise_for_status()
            root = ET.fromstring(resp.content)
        except Exception as e:
            print(f"  WARNING: failed to fetch/parse {url}: {e}")
            continue
        channel = root.find("channel")
        feed_items = channel.findall("item") if channel is not None else []
        print(f"  {url.rsplit('/', 1)[-1]}: {len(feed_items)} item(s)")
        for it in feed_items:
            items.append({
                "title": (it.findtext("title") or "").strip(),
                "link": (it.findtext("link") or "").strip(),
                "description": it.findtext("description") or "",
            })
    return items


def _map_item(item: dict) -> dict | None:
    title = html.unescape(item["title"]).strip().rstrip(",").strip()
    link = item["link"]
    if not title or not link:
        return None

    desc_clean = _clean(item["description"])
    main_iso, main_raw, loi_iso = _extract_deadlines(desc_clean)

    # Solicitation number (e.g. "NSF 26-508") for context in the description.
    sol = re.search(r"NSF\s?\d{2}-\d{3}", desc_clean)
    sol_no = sol.group(0) if sol else None

    haystack = f"{title} {desc_clean}"
    sectors = _infer_sectors(haystack)

    # Build a concise description: trim the "Available Formats / HTML" prefix
    # some announcement items carry, and the trailing feed boilerplate.
    body = re.sub(r"^Available Formats:.*?(solicitation|/\d+)\s*", "", desc_clean, flags=re.I).strip()
    body = re.sub(r"\s*More at https?://\S+.*$", "", body).strip()
    body = re.sub(r"\s*This is an NSF .*?item\.?\s*$", "", body).strip()
    body = body or desc_clean
    description = (f"[{sol_no}] " if sol_no else "") + body
    description = description[:1000] or None

    return {
        "grant_title":              title,
        "funder_name":              "National Science Foundation",
        "source_url":               link,
        "application_portal_url":   link,
        "description":              description,
        "application_deadline":     main_iso,
        "application_deadline_raw": main_raw,
        "eoi_deadline":             loi_iso if loi_iso and loi_iso != main_iso else None,
        "grant_opening_date":       None,
        # Listed in NSF's open-opportunity feeds → currently accepting proposals.
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "ai_focused":               bool(_AI_PATTERN.search(haystack)),
        "thematic_sectors":         sectors,
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_nsf",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{link}|{title}|{main_iso}".encode()
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
    parser = argparse.ArgumentParser(description="NSF open opportunities → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching NSF open funding opportunities (RSS) …")
    raw = _fetch_opportunities()
    print(f"  {len(raw)} raw item(s) retrieved.")

    mapped: list[dict] = []
    seen: set[str] = set()
    for it in raw:
        g = _map_item(it)
        if not g or not g.get("source_url") or not g.get("grant_title"):
            continue
        if g["source_url"] in seen:        # dedup by URL across the two feeds
            continue
        seen.add(g["source_url"])
        mapped.append(g)
    print(f"  {len(mapped)} unique open opportunities to upsert.")

    if args.dry_run:
        print("\n[DRY RUN] First 3 records:")
        for g in mapped[:3]:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(mapped)} records.")
        return

    conn = _connect()
    try:
        counts = {"inserted": 0, "updated": 0, "skipped": 0}
        with conn.cursor() as cur:
            for g in mapped:
                counts[_upsert_grant(cur, g)] += 1
        conn.commit()
    finally:
        conn.close()

    print(f"\nDone: {counts['inserted']} inserted, {counts['updated']} updated, "
          f"{counts['skipped']} skipped.")


if __name__ == "__main__":
    main()
