#!/usr/bin/env python3
"""
Normalize categorical near-duplicate values directly in the database.

audit_contamination.py found three case/hyphen variant pairs still present
despite an earlier source-code cleanup pass. Two had a real source fix
(govai.py and pacific_forum.py both literally wrote "Early-Career
Professional" with a hyphen instead of "Early Career Professional", now
fixed). The other two variants ('Non-profit Organisation' and
'Mid-career Researcher') don't currently exist in any connector's source
code, meaning they're stale rows from an earlier version of some
connector's logic. Rather than archaeology-dig through git history to find
which file used to write them, this directly normalizes every array
column in the database — safe and idempotent regardless of origin.

Usage (on the VPS):
    export $(grep DATABASE_URL Stage_3_LLM_extraction/.env | xargs)
    python3 Stage_2_api_connectors/fix_categorical_variants.py
"""

import os
import sys

import psycopg2

# (column, wrong_value, correct_value)
FIXES = [
    ("organisation_types",     "Non-profit Organisation",     "Non-Profit Organisation"),
    ("individual_eligibility", "Mid-career Researcher",       "Mid-Career Researcher"),
    ("individual_eligibility", "Early-Career Professional",   "Early Career Professional"),
]


def main():
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("ERROR: DATABASE_URL not set.")
    conn = psycopg2.connect(url)
    cur = conn.cursor()

    for col, wrong, correct in FIXES:
        cur.execute(
            f"""
            UPDATE grants
            SET {col} = array_replace({col}, %s, %s)
            WHERE %s = ANY({col})
            RETURNING id
            """,
            (wrong, correct, wrong),
        )
        rows = cur.fetchall()
        print(f"  {col}: '{wrong}' -> '{correct}'  ({len(rows)} record(s))")

    conn.commit()
    conn.close()
    print("\nDone. Re-export grants.json to push these fixes live.")


if __name__ == "__main__":
    main()
