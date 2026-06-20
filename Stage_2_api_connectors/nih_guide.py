#!/usr/bin/env python3
"""
NIH connector — Stage 2 API source.

Uses the NIH RePORTER API v2 (api.reporter.nih.gov) to fetch currently
active NIH-funded projects. The NIH Guide RSS feeds block server IPs (403);
RePORTER is the public alternative that works.

API docs: https://api.reporter.nih.gov/

Usage (on the VPS):
    export $(grep DATABASE_URL /opt/grantglobe/Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/nih_guide.py [--dry-run]
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

REPORTER_URL = "https://api.reporter.nih.gov/v2/projects/search"

ACTIVITY_CODE_SECTORS: dict[str, list[str]] = {
    "R01": ["Health Sciences", "Research & Innovation"],
    "R21": ["Health Sciences", "Research & Innovation"],
    "R03": ["Health Sciences", "Research & Innovation"],
    "R15": ["Health Sciences", "Research & Innovation"],
    "R34": ["Health Sciences", "Research & Innovation"],
    "K01": ["Health Sciences", "Research & Innovation"],
    "K08": ["Health Sciences", "Research & Innovation"],
    "K23": ["Health Sciences", "Research & Innovation"],
    "K99": ["Health Sciences", "Research & Innovation"],
    "F30": ["Health Sciences", "Education & Training"],
    "F31": ["Health Sciences", "Education & Training"],
    "F32": ["Health Sciences", "Education & Training"],
    "T32": ["Health Sciences", "Education & Training"],
    "P01": ["Health Sciences", "Research & Innovation"],
    "U01": ["Health Sciences", "Research & Innovation"],
    "DP1": ["Health Sciences", "Research & Innovation"],
    "DP2": ["Health Sciences", "Research & Innovation"],
}

AGENCY_FUNDER_MAP: dict[str, str] = {
    "NCI":   "National Cancer Institute",
    "NHLBI": "National Heart, Lung, and Blood Institute",
    "NIAID": "National Institute of Allergy and Infectious Diseases",
    "NIMH":  "National Institute of Mental Health",
    "NIDA":  "National Institute on Drug Abuse",
    "NIA":   "National Institute on Aging",
    "NIBIB": "National Institute of Biomedical Imaging and Bioengineering",
    "NIGMS": "National Institute of General Medical Sciences",
    "NIMHD": "National Institute on Minority Health and Health Disparities",
    "NHGRI": "National Human Genome Research Institute",
    "NIDDK": "National Institute of Diabetes and Digestive and Kidney Diseases",
    "NEI":   "National Eye Institute",
    "NIDCD": "National Institute on Deafness and Other Communication Disorders",
    "NINDS": "National Institute of Neurological Disorders and Stroke",
    "NICHD": "Eunice Kennedy Shriver National Institute of Child Health and Human Development",
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
    # Handle ISO 8601 with time component
    if "T" in date_str:
        date_str = date_str.split("T")[0]
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(date_str, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


def _fetch_nih_opportunities() -> list[dict]:
    """
    Fetch active NIH-funded projects via the NIH RePORTER API v2.

    Filters: fiscal years 2024-2026 AND project end date in the future
    (i.e., award is still active). Returns up to 2000 records.
    """
    session = requests.Session()
    session.headers.update({
        "Content-Type": "application/json",
        "Accept": "application/json",
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36"
        ),
    })

    INCLUDE_FIELDS = [
        "ProjectTitle", "ProjectNum", "ProjectStartDate", "ProjectEndDate",
        "AbstractText", "AgencyCode", "FundingMechanism",
        "TotalCost", "DirectCostAmt", "ProjectSerialNum",
    ]

    all_projects: list[dict] = []
    offset = 0
    limit = 500
    max_records = 2000

    while offset < max_records:
        payload = {
            "criteria": {
                "fiscal_years": [2024, 2025, 2026],
                "project_end_date": {
                    "from_date": datetime.date.today().strftime("%Y-%m-%d"),
                },
            },
            "include_fields": INCLUDE_FIELDS,
            "offset": offset,
            "limit": limit,
            "sort_field": "project_start_date",
            "sort_order": "desc",
        }
        try:
            resp = session.post(REPORTER_URL, json=payload, timeout=30)
            resp.raise_for_status()
            data = resp.json()
            results = data.get("results", [])
            if not results:
                break
            all_projects.extend(results)
            total = int(data.get("meta", {}).get("total", 0) or 0)
            cap = min(total, max_records) if total else "?"
            print(f"  NIH RePORTER: fetched {len(all_projects)}/{cap} …")
            if len(results) < limit:
                break
            offset += limit
            time.sleep(0.3)
        except Exception as e:
            print(f"  NIH RePORTER failed at offset {offset}: {e}")
            break

    print(f"  NIH: {len(all_projects)} active project records retrieved.")
    return all_projects


def _map_opportunity(project: dict) -> dict | None:
    """
    Map one NIH RePORTER project to a GrantGlobe grant dict.

    NIH RePORTER API v2 returns snake_case field names, e.g.:
      project_title, project_num, project_start_date, project_end_date,
      abstract_text, agency_code, total_cost, project_serial_num
    """
    title    = html.unescape((project.get("project_title") or "").strip())
    proj_num = (project.get("project_num") or "").strip()
    if not title or not proj_num:
        return None

    serial = project.get("project_serial_num") or proj_num
    portal_url = f"https://reporter.nih.gov/project-details/{serial}"

    open_date    = _parse_date(project.get("project_start_date"))
    deadline_iso = _parse_date(project.get("project_end_date"))

    agency_code = (project.get("agency_code") or "NIH").strip()
    funder = AGENCY_FUNDER_MAP.get(
        agency_code,
        f"NIH – {agency_code}" if agency_code != "NIH" else "National Institutes of Health"
    )

    # Activity code from project number prefix (e.g. "R01CA123456" → "R01")
    m_code = re.match(r'^([A-Z]\d{2})', proj_num)
    activity_code = m_code.group(1) if m_code else ""
    thematic_sectors = ACTIVITY_CODE_SECTORS.get(
        activity_code, ["Health Sciences", "Research & Innovation"]
    )
    grant_type = "Fellowship" if activity_code.startswith(("F", "K", "T")) else "Research Grant"

    total_cost = project.get("total_cost") or project.get("direct_cost_amt")
    try:
        funding_max = float(total_cost) if total_cost else None
    except (ValueError, TypeError):
        funding_max = None

    abstract = html.unescape((project.get("abstract_text") or "").strip())
    description = abstract[:500] if abstract else None

    return {
        "grant_title":              title,
        "funder_name":              funder,
        "source_url":               portal_url,
        "application_portal_url":   None,   # portal_url is unique per record; NULL lets the export uniqueness check use source_url
        "description":              description,
        "application_deadline":     deadline_iso,
        "application_deadline_raw": project.get("project_end_date"),
        "grant_opening_date":       open_date,
        "current_status":           "Open",
        "source_language":          "en",
        "funding_amount_min":       None,
        "funding_amount_max":       funding_max,
        "currency":                 "USD" if funding_max else None,
        "thematic_sectors":         thematic_sectors,
        "grant_types":              [grant_type],
        "applicant_base_regions":   ["North America"],
        "geographic_focus_regions": ["North America"],
        "applicant_base_countries": ["US"],
        "geographic_focus_countries": [],
        "organisation_types":       [],
        "individual_eligibility":   [],
        "domain":                   "api_nih_guide",
        "review_status":            "approved",
        "requires_review":          False,
        "crawl_date":               datetime.date.today().isoformat(),
        "content_hash":             hashlib.sha256(
            f"{proj_num}|{title}|{deadline_iso}".encode()
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
    parser = argparse.ArgumentParser(description="NIH RePORTER → GrantGlobe ingestor")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    print("Fetching NIH active funded projects …")
    projects = _fetch_nih_opportunities()
    print(f"  {len(projects)} raw records retrieved.")

    today = datetime.date.today()
    mapped = []
    for p in projects:
        g = _map_opportunity(p)
        if not g or not g.get("source_url") or not g.get("grant_title"):
            continue
        # Keep projects whose award end date is in the future (or unknown)
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
