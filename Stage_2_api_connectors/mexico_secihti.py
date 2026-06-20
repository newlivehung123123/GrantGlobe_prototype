#!/usr/bin/env python3
"""
SECIHTI (Secretaría de Ciencia, Humanidades, Tecnología e Innovación, Mexico)
connector — Stage 2 API source.

SECIHTI is the renamed successor to CONAHCYT (formerly CONACYT), Mexico's
federal science/humanities/technology agency. Scrapes open "convocatorias"
from secihti.mx/estatus-convocatoria/abierta/ (the open-status filtered
archive). No API key required. Server-rendered WordPress/Elementor archive.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/mexico_secihti.py [--dry-run]
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

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

SECIHTI_BASE = "https://secihti.mx"
SECIHTI_URL = "https://secihti.mx/estatus-convocatoria/abierta/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-MX,es;q=0.9,en;q=0.5",
}

_MONTHS_ES_ABBR = {
    "ene": 1, "feb": 2, "mar": 3, "abr": 4, "may": 5, "jun": 6,
    "jul": 7, "ago": 8, "sep": 9, "oct": 10, "nov": 11, "dic": 12,
}

# Title links to individual convocatoria detail pages
_TITLE_LINK_PAT = re.compile(
    r'<a\s[^>]*href="(https://secihti\.mx/convocatoria/[^"#?]+/?)"[^>]*>(.*?)</a>',
    re.DOTALL | re.IGNORECASE,
)
_DATE_ES_ABBR_PAT = re.compile(
    r'(\d{1,2})\s+([A-Za-záéíóúñ]{3})\.?\s+(\d{4})', re.IGNORECASE
)


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


def _parse_date_es_abbr(text: str) -> tuple[str | None, str | None]:
    m = _DATE_ES_ABBR_PAT.search(text)
    if not m:
        return None, None
    day, month_abbr, year = m.groups()
    month = _MONTHS_ES_ABBR.get(month_abbr.lower()[:3])
    if not month:
        return None, None
    try:
        d = datetime.date(int(year), month, int(day))
        return d.isoformat(), m.group(0).strip()
    except ValueError:
        return None, None


def _fetch(url: str) -> str | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=30)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        print(f"  WARNING: fetch failed for {url}: {e}")
        return None


def _fetch_convocatorias() -> list[dict]:
    """
    Extract open SECIHTI convocatorias from the listing HTML.

    Each card has a title link to a detail page, followed by labeled fields
    "Publicación:", "Apertura de solicitudes:", "Cierre:", and optionally
    "Resultados:" — each with a 'DD Mon YYYY' Spanish-abbreviated date. We
    scan forward from each title link to the next title link (or end of
    document) and extract whichever labeled dates appear in that span.
    """
    html_text = _fetch(SECIHTI_URL)
    if not html_text:
        return []

    idx = html_text.find("/convocatoria/")
    if idx > 0:
        print(f"  SECIHTI: first convocatoria link at char {idx} ✓")
    else:
        print("  SECIHTI WARNING: no /convocatoria/ links found on page")
        print(f"  SECIHTI page length: {len(html_text)} chars")
        return []

    links: list[tuple[int, int, str, str]] = []
    seen_urls: set[str] = set()
    for m in _TITLE_LINK_PAT.finditer(html_text):
        url = m.group(1).strip()
        title = _strip_tags(m.group(2)).strip()
        if not title or len(title) < 10 or url in seen_urls:
            continue
        seen_urls.add(url)
        links.append((m.start(), m.end(), url, title))

    convocatorias = []
    for i, (_lstart, lend, url, title) in enumerate(links):
        next_start = links[i + 1][0] if i + 1 < len(links) else len(html_text)
        block = html_text[lend:next_start]
        block_text = _strip_tags(block)

        cierre_idx = block_text.lower().find("cierre:")
        apertura_idx = block_text.lower().find("apertura de solicitudes:")

        close_iso = close_raw = None
        if cierre_idx >= 0:
            close_iso, close_raw = _parse_date_es_abbr(block_text[cierre_idx:cierre_idx + 60])

        open_iso = None
        if apertura_idx >= 0:
            open_iso, _ = _parse_date_es_abbr(block_text[apertura_idx:apertura_idx + 80])

        convocatorias.append({
            "title": title[:300],
            "url": url,
            "open_iso": open_iso,
            "close_iso": close_iso,
            "close_raw": close_raw,
        })

    return convocatorias


def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url = opp.get("url", "").strip()
    if not title or not url:
        return None

    return {
        "grant_title":              title,
        "funder_name":              "Secretaría de Ciencia, Humanidades, Tecnología e Innovación (SECIHTI), Mexico",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              (
            "Convocatoria de la Secretaría de Ciencia, Humanidades, "
            "Tecnología e Innovación (SECIHTI, anteriormente CONAHCYT) de "
            "México. Consulte la convocatoria oficial para bases, requisitos "
            "y fechas completas."
        ),
        "application_deadline":     opp.get("close_iso"),
        "application_deadline_raw": opp.get("close_raw"),
        "grant_opening_date":       opp.get("open_iso"),
        "current_status":           "Open",
        "source_language":          "es",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         ["Research & Innovation", "Education & Training"],
        "grant_types":              ["Research Grant", "Fellowship"],
        "applicant_base_regions":   ["Latin America & Caribbean"],
        "geographic_focus_regions": ["Latin America & Caribbean"],
        "applicant_base_countries": ["MX"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_mexico_secihti",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{url}|{title}|{opp.get('close_iso')}".encode()
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
    parser = argparse.ArgumentParser(description="SECIHTI Mexico → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching SECIHTI Mexico open convocatorias page …")
    raw_opps = _fetch_convocatorias()
    print(f"  {len(raw_opps)} raw records scraped.")

    today = datetime.date.today()
    mapped = []
    for o in raw_opps:
        g = _map_opportunity(o)
        if not g:
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
        print("\n[DRY RUN] Full records:")
        for g in deduped:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
        return

    conn = _connect()
    counts = {"inserted": 0, "updated": 0, "skipped": 0}
    try:
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
