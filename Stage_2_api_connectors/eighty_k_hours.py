#!/usr/bin/env python3
"""
80,000 Hours job board connector — Stage 2 API source (funding only).

Source: https://jobs.80000hours.org/  (Algolia-backed search index `jobs_prod`)

The board is mostly jobs, but its `tags_role_type` facet separates out
**Funding** and **Fellowship** opportunities — the only types GrantGlobe (a
funding engine) ingests here. Everything else (Full-time/Part-time/Internship/
Volunteering/Course/Other) is excluded.

The Algolia application id + search-only API key are the public ones embedded in
the board's own front-end (read-only search access).

Overlaps heavily with the EA Opportunities board — cross-source de-duplication
is handled at export time on normalised (title + funder).

Usage:
    python3 Stage_2_api_connectors/eighty_k_hours.py [--dry-run]
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

import psycopg2
import requests
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

ALGOLIA_APP_ID = "W6KM1UDIB3"
ALGOLIA_API_KEY = "d1d7f2c8696e7b36837d5ed337c4a319"   # public search-only key
ALGOLIA_INDEX = "jobs_prod"
DOMAIN = "api_80k_hours"

# Funding-relevant role types (per user scope). 80k has no "Contest" type.
ROLE_TYPES = ["Funding", "Fellowship"]

_HEADERS = {"Content-Type": "application/json",
            "X-Algolia-Application-Id": ALGOLIA_APP_ID,
            "X-Algolia-API-Key": ALGOLIA_API_KEY}

_SECTOR_KEYWORDS: list[tuple[re.Pattern, list[str]]] = [
    (re.compile(r"\b(ai|artificial intelligence|machine learning|alignment|agi)\b", re.I),
        ["Artificial Intelligence", "Science & Technology"]),
    (re.compile(r"(information security|cyber|infosec)", re.I),
        ["Information & Communication Technologies"]),
    (re.compile(r"(biosecur|pandemic|biolog|biorisk|health security)", re.I),
        ["Health Sciences", "Global Health"]),
    (re.compile(r"(global health|public health|disease|medic)", re.I),
        ["Global Health", "Health Sciences"]),
    (re.compile(r"(animal|welfare of)", re.I), ["Animal Welfare"]),
    (re.compile(r"(climate|environment|clean energy)", re.I), ["Climate & Environment"]),
    (re.compile(r"(policy|governance|geopolit)", re.I), ["Social Sciences & Humanities"]),
    (re.compile(r"(global priorit|economic|development|poverty)", re.I),
        ["Social Sciences & Humanities"]),
]
_AI_PATTERN = re.compile(r"\b(artificial intelligence|machine learning|\bai\b|alignment|agi|deep learning)\b", re.I)

_COUNTRY = {
    "united kingdom": ("GB", "Europe"), "uk": ("GB", "Europe"), "england": ("GB", "Europe"),
    "united states": ("US", "North America"), "usa": ("US", "North America"), "us": ("US", "North America"),
    "canada": ("CA", "North America"), "germany": ("DE", "Europe"), "france": ("FR", "Europe"),
    "netherlands": ("NL", "Europe"), "switzerland": ("CH", "Europe"), "spain": ("ES", "Europe"),
    "australia": ("AU", "Asia-Pacific"), "india": ("IN", "Asia-Pacific"), "singapore": ("SG", "Asia-Pacific"),
    "china": ("CN", "Asia-Pacific"), "japan": ("JP", "Asia-Pacific"),
    "kenya": ("KE", "Sub-Saharan Africa"), "nigeria": ("NG", "Sub-Saharan Africa"),
}
_REGION_ORDER = ["North America", "Europe", "Asia-Pacific", "Sub-Saharan Africa"]


def _get_db_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if not url:
        env_path = os.path.join(os.path.dirname(__file__), "..", "Stage_3_LLM_extraction", ".env")
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


def _clean(text: str | None) -> str:
    if not text:
        return ""
    text = re.sub(r"<[^>]+>", " ", text)
    text = html.unescape(text)
    return re.sub(r"\s+", " ", text).strip()


def _infer_sectors(text: str) -> list[str]:
    out: list[str] = []
    for pat, secs in _SECTOR_KEYWORDS:
        if pat.search(text):
            for s in secs:
                if s not in out:
                    out.append(s)
    return out or ["Research & Innovation"]


def _epoch_to_iso(ts) -> str | None:
    try:
        ts = int(ts)
    except (TypeError, ValueError):
        return None
    if ts <= 0:
        return None
    try:
        d = datetime.datetime.fromtimestamp(ts, datetime.timezone.utc).date()
    except (OverflowError, OSError, ValueError):
        return None
    if d.year > 2100:        # far-future sentinel = rolling / no real deadline
        return None
    return d.isoformat()


def _canonical_url(url: str) -> str:
    """Drop 80k's UTM/tracking query params so the link is the funder's clean URL."""
    if not url:
        return url
    parts = urlsplit(url)
    kept = [(k, v) for k, v in parse_qsl(parts.query)
            if not k.lower().startswith("utm_") and k.lower() not in ("source", "medium", "ref")]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def _geo(countries: list[str]) -> tuple[list[str], list[str]]:
    isos: list[str] = []
    regions: list[str] = []
    for c in countries or []:
        key = str(c).strip().lower()
        if key in _COUNTRY:
            iso, region = _COUNTRY[key]
            if iso not in isos:
                isos.append(iso)
            if region not in regions:
                regions.append(region)
    if not regions:
        regions = ["Global"]
    regions.sort(key=lambda r: _REGION_ORDER.index(r) if r in _REGION_ORDER else 99)
    return (regions, isos)


def _grant_types(role_types: list[str]) -> list[str]:
    out = []
    for t in role_types or []:
        if t == "Funding" and "Grant" not in out:
            out.append("Grant")
        elif t == "Fellowship" and "Fellowship" not in out:
            out.append("Fellowship")
    return out or ["Grant"]


def _fetch_hits() -> list[dict]:
    """Page through the Algolia index for Funding + Fellowship role types."""
    url = f"https://{ALGOLIA_APP_ID}-dsn.algolia.net/1/indexes/{ALGOLIA_INDEX}/query"
    facet = [[f"tags_role_type:{rt}" for rt in ROLE_TYPES]]   # OR across role types
    hits: list[dict] = []
    page = 0
    while True:
        body = {
            "hitsPerPage": 200, "page": page, "query": "", "facetFilters": facet,
            "attributesToRetrieve": [
                "title", "company_name", "company", "url_external", "closes_at",
                "posted_at", "tags_country", "tags_area", "tags_skill",
                "tags_role_type", "description_short", "description", "objectID",
            ],
        }
        r = requests.post(url, headers=_HEADERS, data=json.dumps(body), timeout=30)
        r.raise_for_status()
        d = r.json()
        hits.extend(d.get("hits", []))
        if page >= d.get("nbPages", 1) - 1:
            break
        page += 1
    return hits


def _map_hit(h: dict) -> dict | None:
    title = _clean(h.get("title"))
    funder = (h.get("company_name") or (h.get("company") or {}).get("name") or "").strip() \
        if isinstance(h.get("company"), dict) else (h.get("company_name") or "").strip()
    link = _canonical_url((h.get("url_external") or "").strip())
    if not title or not link or not funder:
        return None

    deadline = _epoch_to_iso(h.get("closes_at"))
    today = datetime.date.today().isoformat()
    status = "Closed" if (deadline and deadline < today) else "Open"

    role_types = h.get("tags_role_type") or []
    if isinstance(role_types, str):
        role_types = [role_types]
    areas = h.get("tags_area") or []
    desc = _clean(h.get("description_short") or h.get("description"))[:900] or None
    haystack = f"{title} {' '.join(areas)} {desc or ''}"
    regions, countries = _geo(h.get("tags_country") or [])

    return {
        "grant_title":              title,
        "funder_name":              funder,
        "source_url":               link,
        "application_portal_url":   link,
        "description":              desc,
        "application_deadline":     deadline,
        "application_deadline_raw": (f"Closes {deadline}" if deadline else "Rolling / see listing"),
        "eoi_deadline":             None,
        "grant_opening_date":       _epoch_to_iso(h.get("posted_at")),
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "ai_focused":               bool(_AI_PATTERN.search(haystack)),
        "thematic_sectors":         _infer_sectors(haystack),
        "grant_types":              _grant_types(role_types),
        "applicant_base_regions":   regions,
        "geographic_focus_regions": regions,
        "applicant_base_countries": countries,
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   DOMAIN,
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today,
        "content_hash":             hashlib.sha256(
            f"{DOMAIN}|{h.get('objectID')}|{title}|{link}".encode()
        ).hexdigest(),
    }


def _upsert_grant(cur, g: dict) -> str:
    cur.execute("SELECT id, review_status FROM grants WHERE source_url = %s", (g["source_url"],))
    existing = cur.fetchone()
    if existing:
        if existing[1] == "rejected":
            return "skipped"
        set_clauses = ", ".join(f"{k} = %({k})s" for k in g if k != "source_url")
        cur.execute(f"UPDATE grants SET {set_clauses} WHERE id = %(id)s", {**g, "id": existing[0]})
        return "updated"
    cols = list(g.keys())
    cur.execute(
        f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(f'%({c})s' for c in cols)})", g,
    )
    return "inserted"


def main() -> None:
    parser = argparse.ArgumentParser(description="80,000 Hours funding/fellowships → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching 80,000 Hours board (Algolia, Funding + Fellowship) …")
    raw = _fetch_hits()
    print(f"  {len(raw)} Funding/Fellowship hit(s) retrieved.")

    mapped: list[dict] = []
    seen: set[str] = set()
    for h in raw:
        g = _map_hit(h)
        if not g:
            continue
        if g["source_url"] in seen:
            continue
        seen.add(g["source_url"])
        mapped.append(g)
    print(f"  {len(mapped)} unique opportunities to upsert.")

    if args.dry_run:
        from collections import Counter
        print("  status:", dict(Counter(g["current_status"] for g in mapped)))
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
