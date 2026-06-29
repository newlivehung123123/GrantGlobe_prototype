#!/usr/bin/env python3
"""
EA Opportunities Board connector — Stage 2 API source.

Source: https://www.effectivealtruism.org/opportunities

The board is a Next.js page that ships its full dataset in the page's
``__NEXT_DATA__`` JSON (``props.pageProps.opportunities`` — ~865 records), so we
read it directly rather than scraping the embedded Airtable view.

GrantGlobe is a *funding* engine, so this connector ingests ONLY the
funding-relevant opportunity types — Funding (grants), Fellowship, and Contest
(prizes) — and excludes jobs, internships, volunteering, events, advising, etc.

Each record's funder is the listing organisation and the URL is the board's
``applicationLink`` (the funder's own apply page). Descriptions on this board
are AI-generated (disclosed by the source), so they are ingested as secondary
context only; the authoritative fields are title / funder / link / deadline /
type / cause area.

Overlaps heavily with the 80,000 Hours board — cross-source de-duplication is
handled at export time on normalised (title + funder).

Usage:
    python3 Stage_2_api_connectors/ea_opportunities.py [--dry-run]
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

SOURCE_URL = "https://www.effectivealtruism.org/opportunities"
DOMAIN = "api_ea_opportunities"

# Opportunity types we treat as funding (per user scope: grants, fellowships,
# prizes/contests). Everything else on the board is a job/volunteer/event/etc.
FUNDING_TYPES = {"Funding", "Fellowship", "Contest"}

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml",
}

# cause-area / keyword → GrantGlobe thematic sector(s)
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
    (re.compile(r"(policy|governance|geopolit|security studies)", re.I),
        ["Social Sciences & Humanities"]),
    (re.compile(r"(global priorit|economic|development|poverty)", re.I),
        ["Social Sciences & Humanities"]),
]

_AI_PATTERN = re.compile(r"\b(artificial intelligence|machine learning|\bai\b|alignment|agi|deep learning)\b", re.I)

# country name / code → (ISO alpha-2, region) — only unambiguous signals are mapped.
_COUNTRY = {
    "uk": ("GB", "Europe"), "united kingdom": ("GB", "Europe"), "england": ("GB", "Europe"),
    "us": ("US", "North America"), "usa": ("US", "North America"),
    "united states": ("US", "North America"),
    "canada": ("CA", "North America"), "germany": ("DE", "Europe"),
    "france": ("FR", "Europe"), "netherlands": ("NL", "Europe"),
    "switzerland": ("CH", "Europe"), "australia": ("AU", "Asia-Pacific"),
    "india": ("IN", "Asia-Pacific"), "singapore": ("SG", "Asia-Pacific"),
    "china": ("CN", "Asia-Pacific"), "japan": ("JP", "Asia-Pacific"),
    "kenya": ("KE", "Sub-Saharan Africa"), "nigeria": ("NG", "Sub-Saharan Africa"),
}
_GLOBAL_TOKENS = re.compile(r"\b(remote|global|worldwide|anywhere|various|online|virtual)\b", re.I)


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


def _geo(location: str) -> tuple[list[str], list[str]]:
    """Return (regions, countries) — conservative: only map unambiguous signals."""
    loc = (location or "").strip()
    if not loc or _GLOBAL_TOKENS.search(loc):
        return (["Global"], [])
    low = loc.lower()
    # match a country name/code anywhere (prefer the trailing token after a comma)
    tail = low.split(",")[-1].strip()
    for cand in (tail, low):
        if cand in _COUNTRY:
            iso, region = _COUNTRY[cand]
            return ([region], [iso])
    for name, (iso, region) in _COUNTRY.items():
        if re.search(r"\b" + re.escape(name) + r"\b", low):
            return ([region], [iso])
    return (["Global"], [])


def _types_to_grant_types(types: list[str]) -> list[str]:
    out = []
    for t in types:
        if t == "Funding" and "Grant" not in out:
            out.append("Grant")
        elif t == "Fellowship" and "Fellowship" not in out:
            out.append("Fellowship")
        elif t == "Contest" and "Prize" not in out:
            out.append("Prize")
    return out or ["Grant"]


def _strip_ai_footer(desc: str) -> str:
    # remove the board's AI-generation disclaimer footer
    desc = re.split(r"\*This text was generated by AI", desc)[0]
    return desc.strip()


def _fetch_opportunities() -> list[dict]:
    resp = requests.get(SOURCE_URL, headers=_HEADERS, timeout=40)
    resp.raise_for_status()
    m = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        resp.text, re.S,
    )
    if not m:
        raise RuntimeError("Could not find __NEXT_DATA__ on EA opportunities page")
    data = json.loads(m.group(1))
    ops = data.get("props", {}).get("pageProps", {}).get("opportunities")
    if not isinstance(ops, list):
        raise RuntimeError("Unexpected EA page structure (no opportunities list)")
    return ops


def _map_item(o: dict) -> dict | None:
    types = [t for t in (o.get("opportunityTypes") or []) if isinstance(t, str)]
    if not (set(types) & FUNDING_TYPES):
        return None

    title = _clean(o.get("title"))
    orgs = o.get("organizations") or []
    funder = ""
    if orgs and isinstance(orgs[0], dict):
        funder = (orgs[0].get("name") or "").strip()
    if not funder:
        org_alt = o.get("organization") or []
        if isinstance(org_alt, list) and org_alt:
            funder = str(org_alt[0]).strip()
    link = (o.get("applicationLink") or "").strip()
    if not title or not link or not funder:
        return None

    deadline = o.get("applicationDeadline")
    deadline = deadline if isinstance(deadline, str) and re.match(r"\d{4}-\d{2}-\d{2}", deadline) else None
    today = datetime.date.today().isoformat()
    status = "Closed" if (deadline and deadline < today) else "Open"

    causes = [c for c in (o.get("causeAreas") or []) if isinstance(c, str)]
    haystack = f"{title} {' '.join(causes)} {_clean(o.get('description'))}"
    regions, countries = _geo(o.get("location") or "")

    desc = _strip_ai_footer(_clean(o.get("description")))[:900] or None

    return {
        "grant_title":              title,
        "funder_name":              funder,
        "source_url":               link,
        "application_portal_url":   link,
        "description":              desc,
        "application_deadline":     deadline,
        "application_deadline_raw": (f"Closes {deadline}" if deadline else "Rolling / see listing"),
        "eoi_deadline":             None,
        "grant_opening_date":       None,
        "current_status":           status,
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "ai_focused":               bool(_AI_PATTERN.search(haystack)),
        "thematic_sectors":         _infer_sectors(haystack),
        "grant_types":              _types_to_grant_types(types),
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
            f"{DOMAIN}|{o.get('id')}|{title}|{link}".encode()
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
    parser = argparse.ArgumentParser(description="EA Opportunities Board → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching EA Opportunities Board …")
    raw = _fetch_opportunities()
    print(f"  {len(raw)} total opportunities on the board.")

    mapped: list[dict] = []
    seen: set[str] = set()
    for o in raw:
        g = _map_item(o)
        if not g:
            continue
        if g["source_url"] in seen:
            continue
        seen.add(g["source_url"])
        mapped.append(g)
    print(f"  {len(mapped)} funding/fellowship/contest opportunities to upsert.")

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
