#!/usr/bin/env python3
"""
GrantGlobe — Spain AEI (Agencia Estatal de Investigación) connector.

Fetches open research calls from the AEI grant portal by:
  1. Scraping the open-calls listing page for detail-page slugs
  2. Visiting each detail page and extracting title, deadline, description

Usage:
    export DATABASE_URL=...
    python3 Stage_2_api_connectors/spain_aei.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import sys

import psycopg2
import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

AEI_BASE    = "https://www.aei.gob.es"
AEI_LISTING = f"{AEI_BASE}/convocatorias/buscador-convocatorias?status=1"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "es-ES,es;q=0.9,en;q=0.8",
}

ES_MONTHS = {
    "enero": 1,     "febrero": 2,  "marzo": 3,     "abril": 4,
    "mayo": 5,      "junio": 6,    "julio": 7,     "agosto": 8,
    "septiembre": 9,"octubre": 10, "noviembre": 11, "diciembre": 12,
}

# ── helpers ──────────────────────────────────────────────────────────────────

def _text_only(html: str) -> str:
    """Strip <script>, <style>, and all tags; collapse whitespace."""
    html = re.sub(r'<script[^>]*>.*?</script>', ' ', html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', ' ', html,
                  flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<[^>]+>', ' ', html)
    return re.sub(r'\s+', ' ', html).strip()


def _parse_es_date(text: str) -> datetime.date | None:
    """
    Parse Spanish date patterns such as "1 de julio de 2026" or
    "10 de junio a 1 de julio de 2026" (deadline range → last date).
    Returns None if the date is more than two years in the past.
    """
    pat = re.compile(
        r'(\d{1,2})\s+de\s+'
        r'(enero|febrero|marzo|abril|mayo|junio|julio|agosto|'
        r'septiembre|octubre|noviembre|diciembre)'
        r'\s+(?:de\s+)?(\d{4})',
        re.IGNORECASE,
    )
    matches = list(pat.finditer(text))
    if not matches:
        return None
    m = matches[-1]                      # last date = closing date for ranges
    day   = int(m.group(1))
    month = ES_MONTHS.get(m.group(2).lower(), 0)
    year  = int(m.group(3))
    if not month:
        return None
    try:
        d = datetime.date(year, month, day)
        if d < datetime.date.today() - datetime.timedelta(days=730):
            return None
        return d
    except ValueError:
        return None


def _fetch(url: str, session: requests.Session) -> str:
    resp = session.get(url, headers=HEADERS, timeout=20, verify=False)
    resp.encoding = "utf-8"
    resp.raise_for_status()
    return resp.text


# ── scraping ─────────────────────────────────────────────────────────────────

def _get_detail_urls(session: requests.Session) -> list[str]:
    """Return all unique detail-page URLs from the open-calls listing."""
    html = _fetch(AEI_LISTING, session)
    slugs = list(dict.fromkeys(
        re.findall(
            r'href="(/convocatorias/buscador-convocatorias/[a-z0-9][a-z0-9\-]+)"',
            html,
        )
    ))
    urls = [AEI_BASE + s for s in slugs]
    print(f"  AEI: {len(urls)} open-call links found")
    return urls


def _parse_detail(url: str, session: requests.Session) -> dict | None:
    """Fetch and parse a single AEI call detail page."""
    try:
        html = _fetch(url, session)
    except Exception as e:
        print(f"  AEI: fetch error {url}: {e}")
        return None

    text = _text_only(html)

    # ── title ────────────────────────────────────────────────────────────────
    title = ""
    tm = re.search(r'<title>(.*?)</title>', html, re.DOTALL | re.IGNORECASE)
    if tm:
        title = re.sub(r'<[^>]+>', '', tm.group(1)).strip()
        # Strip "| Agencia Estatal de Investigación" suffix
        title = re.split(r'\s*[|–—]\s*(?:Agencia|AEI)\b', title)[0].strip()
    if not title or len(title) < 5:
        return None

    # ── deadline ─────────────────────────────────────────────────────────────
    deadline: datetime.date | None = None
    deadline_raw = ""

    # Look for "Plazo de presentación de solicitudes: <date range>"
    plazo_m = re.search(
        r'Plazo[^:]{0,100}:\s*(.{10,300}?)(?=\s{2,}|\.|<|$)',
        text,
        re.IGNORECASE,
    )
    if plazo_m:
        deadline_raw = plazo_m.group(1).strip()
        deadline = _parse_es_date(deadline_raw)

    # Fallback: any date-range sentence mentioning "presentación" or "solicitud"
    if not deadline:
        for pat in [
            r'presentaci[oó]n\b[^.]{0,200}(\d{1,2}\s+de\s+\w+[^.]{0,100})',
            r'hasta\s+el\s+(\d{1,2}\s+de\s+\w+[^.]{0,80})',
        ]:
            fm = re.search(pat, text, re.IGNORECASE)
            if fm:
                deadline_raw = fm.group(1).strip()
                deadline = _parse_es_date(deadline_raw)
                if deadline:
                    break

    # ── amount ───────────────────────────────────────────────────────────────
    amount_raw = ""
    for pat in [
        r'€\s?[\d.,]+(?:\s?(?:millones?|M))?',
        r'[\d.,]+\s?(?:millones?\s+de\s+)?euros?',
    ]:
        am = re.search(pat, text, re.IGNORECASE)
        if am:
            amount_raw = am.group(0).strip()
            break

    # ── description ──────────────────────────────────────────────────────────
    desc = ""
    for pat in [
        r'Esta convocatoria[^.]{20,}(?:\.[^.]{10,}){0,2}\.',
        r'El objeto de[^.]{20,}\.',
        r'La presente convocatoria[^.]{20,}\.',
        r'[A-ZÁÉÍÓÚÑ][^.]{80,}\.',
    ]:
        dm = re.search(pat, text, re.IGNORECASE)
        if dm:
            candidate = dm.group(0).strip()
            # Skip JS or CSS artifacts
            if not any(kw in candidate for kw in ['window.', 'function', '{', '}']):
                desc = candidate[:500]
                break

    return {
        "title":        title,
        "url":          url,
        "deadline":     deadline,
        "deadline_raw": deadline_raw,
        "amount_raw":   amount_raw,
        "description":  desc,
    }


# ── record builder ───────────────────────────────────────────────────────────

def _build_record(item: dict) -> dict:
    today    = datetime.date.today()
    deadline = item.get("deadline")
    raw_str  = f"{item['title']}|{item.get('deadline_raw','')}|{item.get('description','')}"
    h        = hashlib.sha256(raw_str.encode()).hexdigest()

    return {
        "grant_title":              item["title"],
        "funder_name":              "Spanish State Research Agency (AEI)",
        "source_url":               item["url"],
        "application_portal_url":   item["url"],
        "description":              item.get("description", "")[:500] or None,
        "application_deadline":     deadline.isoformat() if deadline else None,
        "application_deadline_raw": item.get("deadline_raw") or None,
        "grant_opening_date":       None,
        "current_status":           "Open",
        "source_language":          "es",
        "funding_amount_min":       None,
        "funding_amount_max":       None,
        "currency":                 "EUR" if item.get("amount_raw") else None,
        "thematic_sectors":         ["Research & Innovation"],
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["ES"],
        "geographic_focus_countries": [],
        "organisation_types":       ["University", "Research Institution"],
        "individual_eligibility":   [],
        "domain":                   "api_aei",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               today.isoformat(),
        "content_hash":             h,
    }


# ── DB upsert ────────────────────────────────────────────────────────────────

def _upsert(conn, record: dict) -> str:
    cur = conn.cursor()
    cur.execute("SELECT id FROM grants WHERE source_url = %s",
                (record["source_url"],))
    if cur.fetchone():
        cur.execute(
            """UPDATE grants SET
                grant_title = %s, description = %s,
                application_deadline = %s, application_deadline_raw = %s,
                funding_amount_min = %s, funding_amount_max = %s, currency = %s,
                crawl_date = %s, content_hash = %s
               WHERE source_url = %s""",
            (
                record["grant_title"], record["description"],
                record["application_deadline"], record["application_deadline_raw"],
                record["funding_amount_min"], record["funding_amount_max"],
                record["currency"], record["crawl_date"], record["content_hash"],
                record["source_url"],
            ),
        )
        return "updated"
    else:
        cols  = list(record.keys())
        vals  = [record[c] for c in cols]
        cur.execute(
            f"INSERT INTO grants ({', '.join(cols)}) VALUES ({', '.join(['%s']*len(cols))})",
            vals,
        )
        return "inserted"


# ── main ─────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="AEI Spain connector")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print records without writing to DB")
    args = parser.parse_args()

    print("Fetching AEI Spain open calls …")
    session = requests.Session()

    urls = _get_detail_urls(session)
    if not urls:
        print("  AEI: no open-call links found; aborting.")
        sys.exit(1)

    items   = []
    skipped = 0
    for url in urls:
        item = _parse_detail(url, session)
        if item:
            items.append(item)
        else:
            print(f"  AEI: skipped {url}")
            skipped += 1

    print(f"  AEI: {len(items)} calls parsed ({skipped} skipped)")

    records = [_build_record(i) for i in items]

    if args.dry_run:
        print(f"\n[DRY RUN] First 3 records:")
        for r in records[:3]:
            print(json.dumps(r, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(records)} records.")
        return

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(1)

    conn = psycopg2.connect(db_url)
    inserted = updated = err = 0
    for record in records:
        try:
            result = _upsert(conn, record)
            conn.commit()
            if result == "inserted":
                inserted += 1
            else:
                updated += 1
        except Exception as e:
            conn.rollback()
            print(f"  DB error {record['source_url']}: {e}")
            err += 1

    conn.close()
    print(f"\nDone: {inserted} inserted, {updated} updated, {err} errors.")


if __name__ == "__main__":
    main()
