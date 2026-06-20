#!/usr/bin/env python3
"""
Corrected re-check of audit_contamination.py's "no geography" finding.

The original query only checked applicant_base_regions, geographic_focus_regions,
and applicant_base_countries — it forgot geographic_focus_countries. A record
like GovAI's, which sets geographic_focus_countries=['US'] but leaves the other
three empty, was wrongly flagged as having "zero geography" when it actually
has a country set. This checks all four columns together.

Usage (on the VPS):
    export $(grep DATABASE_URL Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/check_geography_gap.py
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
        SELECT domain, COUNT(*), array_agg(grant_title)
        FROM grants
        WHERE review_status = 'approved'
          AND COALESCE(array_length(applicant_base_regions, 1), 0) = 0
          AND COALESCE(array_length(geographic_focus_regions, 1), 0) = 0
          AND COALESCE(array_length(applicant_base_countries, 1), 0) = 0
          AND COALESCE(array_length(geographic_focus_countries, 1), 0) = 0
        GROUP BY domain ORDER BY COUNT(*) DESC
    """)
    rows = cur.fetchall()
    if not rows:
        print("None found — every record has geography set in at least one of the four fields.")
    else:
        total = sum(r[1] for r in rows)
        print(f"{total} record(s) across {len(rows)} domain(s) with ALL FOUR geography fields empty:\n")
        for domain, cnt, titles in rows:
            print(f"  {domain}: {cnt}")
            for t in titles[:3]:
                print(f"      - {t}")

    conn.close()


if __name__ == "__main__":
    main()
