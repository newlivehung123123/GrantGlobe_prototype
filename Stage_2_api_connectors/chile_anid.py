#!/usr/bin/env python3
"""
ANID (Agencia Nacional de Investigación y Desarrollo, Chile) connector — Stage 2 API source.

Scrapes open "concursos" (funding competitions) from anid.cl/concursos/.
No API key required. Server-rendered WordPress/Elementor archive.

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/chile_anid.py [--dry-run]
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

ANID_BASE = "https://anid.cl"
ANID_URL = "https://anid.cl/concursos/"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-CL,es;q=0.9,en;q=0.5",
}

_MONTHS_ES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10,
    "noviembre": 11, "diciembre": 12,
}

# Each call's permalink appears twice per card (image wrapper, then "Ver más"
# link) — both pointing at the same /concursos/{slug}/ detail URL. We use the
# span between a URL's first and second occurrence as that card's content
# block, since category, title, and dates all sit in that span.
_DETAIL_LINK_PAT = re.compile(
    r'<a\s[^>]*href="(https://anid\.cl/concursos/(?!jsf/)[a-z0-9\-]+/?)"',
    re.IGNORECASE,
)
_DATE_ES_PAT = re.compile(
    r'(\d{1,2})\s+de\s+([a-záéíóúñ]+)(?:,)?\s+de\s+(\d{4})', re.IGNORECASE
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


def _parse_date_es(text: str) -> tuple[str | None, str | None]:
    """Parse 'DD de MES[,] de YYYY' Spanish date. Returns (iso, raw)."""
    m = _DATE_ES_PAT.search(text)
    if not m:
        return None, None
    day, month_name, year = m.groups()
    month = _MONTHS_ES.get(month_name.lower())
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


def _fetch_concursos() -> list[dict]:
    html_text = _fetch(ANID_URL)
    if not html_text:
        return []

    idx = html_text.find("/concursos/concurso")
    if idx > 0:
        print(f"  ANID: first concurso link at char {idx} ✓")
    else:
        print("  ANID WARNING: no /concursos/concurso-*/ links found on page")
        print(f"  ANID page length: {len(html_text)} chars")
        return []

    # Record every occurrence of every distinct detail URL, in order.
    occurrences: dict[str, list[tuple[int, int]]] = {}
    order: list[str] = []
    for m in _DETAIL_LINK_PAT.finditer(html_text):
        url = m.group(1).rstrip("/") + "/"
        if url not in occurrences:
            occurrences[url] = []
            order.append(url)
        occurrences[url].append((m.start(), m.end()))

    concursos = []
    for url in order:
        spans = occurrences[url]
        if len(spans) < 2:
            # Only one link found for this card (e.g. title not wrapped in a
            # second anchor) — not enough to safely bound a content block.
            continue
        block_start = spans[0][1]
        block_end = spans[-1][0]
        block = html_text[block_start:block_end]
        text = _strip_tags(block)

        # Title: the longest line-like chunk before "Inicio:"
        inicio_idx = text.lower().find("inicio:")
        title_area = text[:inicio_idx] if inicio_idx > 0 else text[:200]
        # Drop a leading category label if present (categories are short,
        # title is the longer trailing segment) — just take the whole
        # remaining chunk; downstream filtering on length handles junk.
        title = title_area.strip()

        cierre_idx = text.lower().find("cierre:")
        inicio_raw = text[inicio_idx:cierre_idx] if (inicio_idx >= 0 and cierre_idx > inicio_idx) else ""
        cierre_segment = text[cierre_idx:cierre_idx + 80] if cierre_idx >= 0 else ""

        open_iso, _ = _parse_date_es(inicio_raw)
        close_iso, close_raw = _parse_date_es(cierre_segment)

        if not title or len(title) < 10:
            continue

        concursos.append({
            "title": title[:300],
            "url": url,
            "open_iso": open_iso,
            "close_iso": close_iso,
            "close_raw": close_raw,
        })

    return concursos


def _map_opportunity(opp: dict) -> dict | None:
    title = opp.get("title", "").strip()
    url = opp.get("url", "").strip()
    if not title or not url:
        return None

    return {
        "grant_title":              title,
        "funder_name":              "Agencia Nacional de Investigación y Desarrollo (ANID), Chile",
        "source_url":               url,
        "application_portal_url":   url,
        "description":              (
            "Concurso de financiamiento de la Agencia Nacional de "
            "Investigación y Desarrollo (ANID) de Chile. Consulte la página "
            "oficial del concurso para bases, requisitos y plazos completos."
        ),
        "application_deadline":     opp.get("close_iso"),
        "application_deadline_raw": opp.get("close_raw"),
        "grant_opening_date":       opp.get("open_iso"),
        "current_status":           "Open",
        "source_language":          "es",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 None,
        "thematic_sectors":         ["Research & Innovation", "Science & Technology"],
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Latin America & Caribbean"],
        "geographic_focus_regions": ["Latin America & Caribbean"],
        "applicant_base_countries": ["CL"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_chile_anid",
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
    parser = argparse.ArgumentParser(description="ANID Chile → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching ANID Chile concursos page …")
    raw_opps = _fetch_concursos()
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
