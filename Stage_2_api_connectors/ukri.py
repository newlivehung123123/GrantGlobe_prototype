#!/usr/bin/env python3
"""
UKRI funding opportunities connector — Stage 2 API source.

Fetches open funding opportunities from the UKRI Funding Finder.
No API key required. Uses the UKRI public search API that powers
the funding finder at https://www.ukri.org/opportunity/

API endpoint:
  GET https://www.ukri.org/wp-json/ukri/v1/opportunities

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/ukri.py [--dry-run]
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import sys
import time

import psycopg2
import requests

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# UKRI WordPress REST API (powers the public funding finder)
UKRI_API_BASE = "https://www.ukri.org/wp-json/ukri/v1/opportunities"
UKRI_OPP_BASE = "https://www.ukri.org/opportunity/"

# Fallback: UKRI sitemap-based scrape target if API unavailable
UKRI_SITEMAP = "https://www.ukri.org/opportunity-sitemap.xml"

COUNCIL_FUNDER_MAP: dict[str, str] = {
    "AHRC": "Arts and Humanities Research Council",
    "BBSRC": "Biotechnology and Biological Sciences Research Council",
    "EPSRC": "Engineering and Physical Sciences Research Council",
    "ESRC": "Economic and Social Research Council",
    "Innovate UK": "Innovate UK",
    "MRC": "Medical Research Council",
    "NERC": "Natural Environment Research Council",
    "NWDAF": "UKRI",
    "STFC": "Science and Technology Facilities Council",
    "RE": "Research England",
}

COUNCIL_SECTOR_MAP: dict[str, list[str]] = {
    "AHRC": ["Arts & Culture", "Humanities & Social Sciences"],
    "BBSRC": ["Health Sciences", "Agriculture & Food"],
    "EPSRC": ["Science & Technology", "Information & Communication Technologies"],
    "ESRC": ["Social Sciences & Humanities", "Economic Development"],
    "Innovate UK": ["Technology & Innovation"],
    "MRC": ["Health Sciences"],
    "NERC": ["Climate & Environment"],
    "STFC": ["Science & Technology", "Space"],
    "RE": ["Education & Training", "Research & Innovation"],
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


def _parse_date(date_str: str | None) -> str | None:
    if not date_str:
        return None
    date_str = str(date_str).strip()
    # Handle ISO 8601 with timezone
    if "T" in date_str:
        date_str = date_str.split("T")[0]
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d %B %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _fetch_ukri_opportunities() -> list[dict]:
    """Fetch UKRI open opportunities from the WordPress REST API."""
    session = requests.Session()
    session.headers.update({
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (compatible; GrantGlobe/1.0)",
    })

    all_opps: list[dict] = []
    page = 1
    per_page = 100

    while True:
        params = {
            "per_page": per_page,
            "page": page,
            "status": "open",
        }
        try:
            resp = session.get(UKRI_API_BASE, params=params, timeout=30)
            if resp.status_code == 404:
                print("  UKRI WP API returned 404 — trying alternate endpoint …")
                return _fetch_ukri_fallback(session)
            resp.raise_for_status()
            data = resp.json()
        except requests.exceptions.JSONDecodeError:
            print("  UKRI API did not return JSON — trying fallback …")
            return _fetch_ukri_fallback(session)
        except Exception as e:
            print(f"  WARNING: UKRI fetch failed at page {page}: {e}")
            if page == 1:
                return _fetch_ukri_fallback(session)
            break

        records = data if isinstance(data, list) else data.get("data") or data.get("opportunities") or []
        if not records:
            break

        all_opps.extend(records)
        total_pages = int(resp.headers.get("X-WP-TotalPages", 1))
        total = int(resp.headers.get("X-WP-Total", len(records)))
        print(f"  UKRI: fetched {len(all_opps)} / {total} …")

        if page >= total_pages or len(records) < per_page:
            break

        page += 1
        time.sleep(0.5)

    return all_opps


def _fetch_ukri_fallback(session: requests.Session) -> list[dict]:
    """
    Fallback: fetch the UKRI opportunities listing page as JSON.
    Tries the /wp-json/wp/v2/posts endpoint filtered by opportunity category.
    """
    print("  Using UKRI fallback endpoint …")
    fallback_url = "https://www.ukri.org/wp-json/wp/v2/posts"
    params = {
        "per_page": 100,
        "page": 1,
        "categories_exclude": "",
        "_fields": "id,title,link,date,acf,meta,excerpt",
    }
    all_opps = []
    for page in range(1, 20):
        params["page"] = page
        try:
            resp = session.get(fallback_url, params=params, timeout=30)
            if resp.status_code in (400, 404):
                break
            resp.raise_for_status()
            records = resp.json()
            if not records:
                break
            # Filter to opportunity posts only (by URL pattern)
            opps = [r for r in records if "/opportunity/" in (r.get("link") or "")]
            all_opps.extend(opps)
            if len(records) < 100:
                break
        except Exception as e:
            print(f"  WARNING: UKRI fallback page {page} failed: {e}")
            break
        time.sleep(0.3)

    print(f"  UKRI fallback: retrieved {len(all_opps)} opportunity posts.")
    return all_opps


def _extract_field(opp: dict, *keys: str) -> str | None:
    """Try multiple key names to extract a field."""
    for k in keys:
        v = opp.get(k)
        if v:
            if isinstance(v, dict):
                v = v.get("rendered") or v.get("raw") or str(v)
            return str(v).strip() or None
    return None


def _map_opportunity(opp: dict) -> dict | None:
    """Map one UKRI record to a GrantGlobe grant dict."""
    title = _extract_field(opp, "title", "post_title", "name")
    if isinstance(title, dict):
        title = title.get("rendered", "")
    title = (title or "").strip()
    if not title:
        return None

    # URL
    portal_url = _extract_field(opp, "link", "url", "permalink", "guid")
    if not portal_url:
        slug = _extract_field(opp, "slug", "post_name")
        if slug:
            portal_url = f"{UKRI_OPP_BASE}{slug}/"

    # Deadline
    acf = opp.get("acf") or opp.get("meta") or {}
    deadline_raw = (
        _extract_field(opp, "closing_date", "deadline", "close_date") or
        (acf.get("closing_date") or acf.get("deadline") if isinstance(acf, dict) else None)
    )
    deadline_iso = _parse_date(deadline_raw)

    open_date_raw = _extract_field(opp, "opening_date", "open_date", "date")
    open_date = _parse_date(open_date_raw)

    # Council / funder
    council_raw = (
        _extract_field(opp, "council", "funding_body", "research_council") or
        (acf.get("council") if isinstance(acf, dict) else None) or ""
    )
    funder = COUNCIL_FUNDER_MAP.get(council_raw, f"UKRI – {council_raw}" if council_raw else "UKRI")
    thematic_sectors = COUNCIL_SECTOR_MAP.get(council_raw, ["Research & Innovation"])

    # Budget
    amount_raw = (
        _extract_field(opp, "total_funding", "funding_amount", "award_amount") or
        (acf.get("total_funding") if isinstance(acf, dict) else None)
    )
    funding_max = None
    if amount_raw:
        import re
        m = re.search(r"[\d,]+", str(amount_raw).replace(",", ""))
        if m:
            try:
                funding_max = float(m.group().replace(",", ""))
            except ValueError:
                pass

    opp_id = str(opp.get("id") or opp.get("ID") or "")

    return {
        "grant_title":              title,
        "funder_name":              funder,
        "source_url":               portal_url,
        "application_portal_url":   portal_url,
        "description":              _extract_field(opp, "excerpt", "description", "content"),
        "application_deadline":     deadline_iso,
        "application_deadline_raw": deadline_raw,
        "grant_opening_date":       open_date,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       funding_max,
        "currency":                 "GBP" if funding_max else None,
        "thematic_sectors":         thematic_sectors,
        "grant_types":              ["Research Grant"],
        "applicant_base_regions":   ["Europe"],
        "geographic_focus_regions": ["Europe"],
        "applicant_base_countries": ["GB"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_ukri",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{opp_id}|{title}|{deadline_iso}".encode()
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
    parser = argparse.ArgumentParser(description="UKRI → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching UKRI funding opportunities …")
    opps = _fetch_ukri_opportunities()
    print(f"  {len(opps)} raw records retrieved.")

    today = datetime.date.today()
    mapped = []
    for o in opps:
        g = _map_opportunity(o)
        if not g or not g.get("source_url") or not g.get("grant_title"):
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
        print("\n[DRY RUN] First 3 records:")
        for g in deduped[:3]:
            print(json.dumps(g, indent=2, default=str))
        print(f"\n[DRY RUN] Would upsert {len(deduped)} records.")
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
