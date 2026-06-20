#!/usr/bin/env python3
"""
Refines audit_contamination.py's "duplicate source_url" finding.

Same source_url + different grant_title is FINE — many funders list
several distinct programmes on one shared page with no per-programme detail
URL, and a well-written upsert keys on (source_url, grant_title) together
so each programme still gets its own row, correctly.

Same source_url + same grant_title is a REAL duplicate — two rows for what
should be a single record, almost certainly because the connector's
upsert lookup didn't actually match an existing row that it should have.

Usage (on the VPS):
    export $(grep DATABASE_URL Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/check_real_dupes.py
"""

import os
import sys

import psycopg2


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("ERROR: DATABASE_URL not set.")
    conn = psycopg2.connect(url)
    cur = conn.cursor()

    cur.execute("""
        SELECT source_url, grant_title, COUNT(*), array_agg(id), array_agg(domain)
        FROM grants
        WHERE review_status = 'approved'
        GROUP BY source_url, grant_title
        HAVING COUNT(*) > 1
        ORDER BY COUNT(*) DESC
    """)
    rows = cur.fetchall()
    if not rows:
        print("No true duplicates (same source_url AND same grant_title). "
              "Everything flagged earlier was distinct programmes sharing a page — not a bug.")
    else:
        print(f"{len(rows)} TRUE duplicate group(s) (same url + same title):\n")
        for source_url, title, cnt, ids, domains in rows:
            print(f"  {cnt}x  [{domains[0]}]  {title}")
            print(f"       {source_url}")
            print(f"       ids: {ids}\n")

    conn.close()


if __name__ == "__main__":
    main()
