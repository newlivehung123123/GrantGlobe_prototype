#!/usr/bin/env python3
"""
One-off cleanup for two issues found by audit_contamination.py:

  1. Null out the deadline on grants.gov records contaminated by the
     2026-06-20/22 platform maintenance window (deadline_raw exactly
     "06/22/2026", crawl_date during the outage). The connector's
     maintenance guard (added separately) prevents this going forward;
     this just cleans up what already got written before the guard existed.
     The real deadline will be restored automatically once grants.gov is
     back up and the connector successfully re-crawls these URLs.

  2. Flip current_status to 'Closed' for any approved record whose
     application_deadline has already passed but is still marked 'Open'
     (or any other non-Closed status). This happens when a call disappears
     from a funder's live listing before its deadline technically arrives,
     so the connector never revisits that URL to update its status.

Usage (on the VPS):
    export $(grep DATABASE_URL Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/fix_immediate.py
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

    print("1. Nulling contaminated grants.gov deadlines (06/22/2026 maintenance artifact) …")
    cur.execute("""
        UPDATE grants
        SET application_deadline = NULL, application_deadline_raw = NULL
        WHERE domain = 'api_grants_gov'
          AND application_deadline_raw = '06/22/2026'
          AND review_status = 'approved'
        RETURNING id
    """)
    fixed = cur.fetchall()
    print(f"   Cleared deadline on {len(fixed)} records.")

    print("\n2. Closing records whose deadline has already passed …")
    cur.execute("""
        UPDATE grants
        SET current_status = 'Closed'
        WHERE review_status = 'approved'
          AND current_status != 'Closed'
          AND application_deadline IS NOT NULL
          AND application_deadline < CURRENT_DATE
        RETURNING id, domain
    """)
    closed = cur.fetchall()
    print(f"   Closed {len(closed)} stale records.")
    from collections import Counter
    by_domain = Counter(d for _, d in closed)
    for domain, cnt in by_domain.most_common():
        print(f"     {domain}: {cnt}")

    conn.commit()
    conn.close()
    print("\nDone. Re-export grants.json to push these fixes live.")


if __name__ == "__main__":
    main()
