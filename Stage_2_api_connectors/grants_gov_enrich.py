#!/usr/bin/env python3
"""
grants_gov_enrich.py — completeness enrichment + source-truth reconciliation
for grants.gov records.

The grants.gov connector (grants_gov.py) ingests SEARCH-level data, which is
sparse (no per-award amount, no eligibility, often no description). This job
calls the grants.gov fetchOpportunity detail API for every api_grants_gov record
and, in a single pass:

  ENRICH      fill funding_amount_min/max (from awardFloor/awardCeiling — NOT the
              total estimatedFunding pool), description (synopsisDesc),
              organisation_types (applicantTypes), application_deadline.
  RECONCILE   update the stored deadline/amount if the source changed; mark an
              opportunity Closed if the API no longer has it (errorcode != 0) or
              it is archived/expired.
  PROVENANCE  stamp last_verified = today on every successfully checked record.

Idempotent and safe to run on a schedule. DRY-RUN unless --apply; --limit N and
--sample for testing.

Usage:
    export $(grep DATABASE_URL ../Stage_3_LLM_extraction/.env | xargs)
    python3 grants_gov_enrich.py [--apply] [--limit N]
"""

from __future__ import annotations

import argparse
import datetime
import html
import re
import sys
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

import psycopg2
import requests
from psycopg2.extras import execute_values

FETCH_URL = "https://api.grants.gov/v1/api/fetchOpportunity"


def _db_url() -> str:
    import os
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    env_path = "../Stage_3_LLM_extraction/.env"
    for cand in (env_path, "Stage_3_LLM_extraction/.env"):
        try:
            for line in open(cand):
                if line.startswith("DATABASE_URL="):
                    return line.split("=", 1)[1].strip().strip('"').strip("'")
        except FileNotFoundError:
            continue
    sys.exit("ERROR: DATABASE_URL not set.")


def _opp_id(source_url: str) -> str | None:
    m = re.search(r"search-results-detail/(\d+)", source_url or "")
    return m.group(1) if m else None


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = re.sub(r"<[^>]+>", " ", html.unescape(text))
    text = re.sub(r"\s+", " ", text).strip()
    return text or None


def _map_applicant_types(types: list[dict]) -> list[str]:
    """Map grants.gov applicantTypes to GrantGlobe's organisation_types vocab."""
    out: set[str] = set()
    for t in types or []:
        tl = (t.get("description") or "").lower()
        if "higher education" in tl or "universit" in tl:
            out.add("University")
        elif "tribal organization" in tl or "nonprofit" in tl or "non-profit" in tl:
            out.add("Non-profit")
        elif "small business" in tl or "for profit" in tl or "for-profit" in tl:
            out.add("For-Profit Company")
        elif ("government" in tl or "school district" in tl
              or "housing authorit" in tl or "tribal" in tl):
            out.add("Government Agency")
        elif "individual" in tl:
            out.add("Individual")
        # "Others" / "Unrestricted" → no specific type
    return sorted(out)


def _parse_close_date(syn: dict) -> str | None:
    raw = syn.get("responseDate") or syn.get("responseDateStr") or ""
    # e.g. "Jul 22, 2026 12:00:00 AM EDT"
    m = re.match(r"([A-Z][a-z]{2,8} \d{1,2}, \d{4})", str(raw))
    if not m:
        return None
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(m.group(1), fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None


_session = requests.Session()
_session.headers.update({"Content-Type": "application/json", "Accept": "application/json"})


def _fetch(opp_id: str) -> dict | None:
    """Return the enrichment dict for one opportunity, or {'_gone': True} if the
    API no longer has it, or None on a transient error (leave record untouched)."""
    try:
        r = _session.post(FETCH_URL, json={"opportunityId": int(opp_id)}, timeout=20)
        r.raise_for_status()
        data = r.json()
    except Exception:
        return None
    if data.get("errorcode") not in (0, "0"):
        return {"_gone": True}          # opportunity withdrawn / not found
    d = data.get("data") or {}
    syn = d.get("synopsis") or {}

    def _num(v):
        try:
            v = float(v)
            return v if v > 0 else None
        except (TypeError, ValueError):
            return None

    return {
        "amount_min": _num(syn.get("awardFloor")),
        "amount_max": _num(syn.get("awardCeiling")),
        "description": _clean(syn.get("synopsisDesc")),
        "org_types": _map_applicant_types(syn.get("applicantTypes")),
        "deadline": _parse_close_date(syn),
        "archived": bool(syn.get("archiveDate")) and _is_past(syn.get("archiveDate")),
    }


def _is_past(raw: str) -> bool:
    m = re.match(r"([A-Z][a-z]{2,8} \d{1,2}, \d{4})", str(raw or ""))
    if not m:
        return False
    for fmt in ("%b %d, %Y", "%B %d, %Y"):
        try:
            return datetime.datetime.strptime(m.group(1), fmt).date() < datetime.date.today()
        except ValueError:
            continue
    return False


def main() -> None:
    ap = argparse.ArgumentParser(description="grants.gov enrich + reconcile")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()

    conn = psycopg2.connect(_db_url(), connect_timeout=30)
    cur = conn.cursor()
    cur.execute("""SELECT id, source_url, funding_amount_max, funding_amount_min,
                          description, organisation_types, application_deadline, current_status
                   FROM grants WHERE domain='api_grants_gov'""")
    rows = cur.fetchall()
    if args.limit:
        rows = rows[: args.limit]
    print(f"api_grants_gov rows to enrich/reconcile: {len(rows)}", flush=True)

    today = datetime.date.today().isoformat()
    enrich_updates = []    # (id, amount_min, amount_max, description, org_types, deadline, status, last_verified)
    gone_ids = []          # records the API no longer has → reconcile to Closed (data left intact)
    stats = Counter()
    t0 = time.time()

    def work(row):
        rid, surl = row[0], row[1]
        oid = _opp_id(surl)
        if not oid:
            return None
        return (row, _fetch(oid))

    with ThreadPoolExecutor(max_workers=12) as pool:
        futs = [pool.submit(work, r) for r in rows]
        done = 0
        for f in as_completed(futs):
            res = f.result()
            done += 1
            if done % 300 == 0:
                print(f"  {done}/{len(rows)} ({time.time()-t0:.0f}s)", flush=True)
            if not res:
                stats["no_oppid"] += 1
                continue
            row, enr = res
            (rid, surl, cur_max, cur_min, cur_desc, cur_ot, cur_dl, cur_status) = row
            if enr is None:
                stats["transient_error"] += 1
                continue
            if enr.get("_gone"):
                # vanished from grants.gov → reconcile to Closed (leave other data intact)
                gone_ids.append(str(rid))
                stats["gone_closed"] += 1
                continue
            # ENRICH (fill missing) + RECONCILE (refresh present)
            new_max = enr["amount_max"] if enr["amount_max"] is not None else (float(cur_max) if cur_max else None)
            new_min = enr["amount_min"] if enr["amount_min"] is not None else (float(cur_min) if cur_min else None)
            new_desc = enr["description"] if (enr["description"] and (not cur_desc or len(cur_desc) < len(enr["description"]))) else cur_desc
            new_ot = enr["org_types"] if enr["org_types"] else (list(cur_ot) if cur_ot else [])
            new_dl = enr["deadline"] or (cur_dl.isoformat() if cur_dl else None)
            new_status = "Closed" if enr.get("archived") else cur_status
            if enr["amount_max"] is not None and cur_max is None: stats["amount_filled"] += 1
            if enr["org_types"] and not cur_ot: stats["eligibility_filled"] += 1
            if enr["description"] and not cur_desc: stats["desc_filled"] += 1
            enrich_updates.append((str(rid), new_min, new_max, new_desc, new_ot, new_dl, new_status, today))

    print(f"\nFetched in {time.time()-t0:.0f}s. Stats: {dict(stats)}", flush=True)
    print(f"Enrich updates: {len(enrich_updates)} | reconcile-to-Closed (vanished): {len(gone_ids)}", flush=True)

    if not args.apply:
        print("DRY-RUN — no writes. Re-run with --apply.", flush=True)
        for u in enrich_updates[:3]:
            print("  sample:", u[0], "max=", u[2], "deadline=", u[5], "status=", u[6], "orgs=", u[4])
        conn.close()
        return

    if enrich_updates:
        execute_values(cur,
            """UPDATE grants AS g SET
                 funding_amount_min = v.amin,
                 funding_amount_max = v.amax,
                 currency = CASE WHEN v.amax IS NOT NULL OR v.amin IS NOT NULL THEN 'USD' ELSE g.currency END,
                 description = v.descr,
                 organisation_types = v.orgs,
                 application_deadline = v.dl::date,
                 current_status = v.status,
                 last_verified = v.lv::date
               FROM (VALUES %s) AS v(id, amin, amax, descr, orgs, dl, status, lv)
               WHERE g.id = v.id::uuid""",
            enrich_updates,
            template="(%s,%s,%s,%s,%s::text[],%s,%s,%s)")
    if gone_ids:
        cur.execute(
            "UPDATE grants SET current_status='Closed', last_verified=%s::date "
            "WHERE id = ANY(%s::uuid[])", (today, gone_ids))
    conn.commit()
    print(f"COMMITTED {len(enrich_updates)} enrich + {len(gone_ids)} reconcile updates.", flush=True)
    conn.close()


if __name__ == "__main__":
    main()
