"""Identify (and, if CONFIRM_DELETE=1, delete) 'grants' rows that are actually
ANR faceted-search listing pages (source_url contains 'tx_solr'), not
individual grant pages. These were ingested before the link_filter fix that
now rejects 'tx_solr' query parameters.

Default mode (no env var) is DRY RUN: prints count + a sample of matching
rows, makes NO changes.

To actually delete, re-run with CONFIRM_DELETE=1 in the environment.

Scope: only rows where source_url contains 'tx_solr' AND
requires_review = true AND review_status = 'pending' — i.e. junk listing
pages still sitting in the review queue. Approved/published rows are never
touched by this script.
"""
import os
from stage3.db import get_connection

conn = get_connection()
cur = conn.cursor()

cur.execute(
    """
    SELECT id, source_url
    FROM grants
    WHERE requires_review = true
      AND review_status = 'pending'
      AND source_url LIKE '%tx_solr%'
    """
)
rows = cur.fetchall()
print(f"matching rows: {len(rows)}")
for gid, source_url in rows[:5]:
    print(f"  id={gid}  url={source_url}")
if len(rows) > 5:
    print(f"  ... and {len(rows) - 5} more")

if os.environ.get("CONFIRM_DELETE") == "1":
    ids = [r[0] for r in rows]
    cur.execute("DELETE FROM grants WHERE id = ANY(%s::uuid[])", (ids,))
    conn.commit()
    print(f"\nDELETED {cur.rowcount} rows.")
else:
    print("\nDRY RUN — no changes made. Re-run with CONFIRM_DELETE=1 to delete.")

cur.close()
conn.close()
