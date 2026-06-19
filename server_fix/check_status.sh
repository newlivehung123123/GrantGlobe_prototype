#!/usr/bin/env bash
# GrantGlobe Stage 3 — one-shot progress report.
set -euo pipefail

S3=/opt/grantglobe/Stage_3_LLM_extraction
cd "$S3"
set -a; source .env; set +a

"$S3/.venv/bin/python" - <<'EOF'
from stage3.db import get_connection

conn = get_connection()
cur = conn.cursor()

print("extraction_log by status:")
cur.execute("SELECT status, COUNT(*) FROM extraction_log GROUP BY status ORDER BY status")
for status, n in cur.fetchall():
    print(f"  {status:12s} {n}")

cur.execute("SELECT COUNT(*) FROM extraction_log WHERE status='completed' AND records_extracted > 0")
print("completed pages that yielded grants:", cur.fetchone()[0])

cur.execute("SELECT COALESCE(SUM(records_extracted),0) FROM extraction_log WHERE status='completed'")
print("total raw grant records extracted:  ", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM grants")
print("grants table total:                 ", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM grants WHERE review_status='approved' OR (requires_review=false AND review_status='pending')")
print("grants visible on the live site:    ", cur.fetchone()[0])

cur.execute("SELECT COUNT(*) FROM grants WHERE requires_review=true AND review_status='pending'")
print("grants held in the review queue:    ", cur.fetchone()[0])

print()
print("top failure reasons (if any):")
cur.execute(
    "SELECT error_message, COUNT(*) FROM extraction_log "
    "WHERE status='failed' GROUP BY error_message ORDER BY COUNT(*) DESC LIMIT 5"
)
for msg, n in cur.fetchall():
    print(f"  {n:5d}  {str(msg)[:100]}")

cur.close()
conn.close()
EOF

echo ""
echo "last 8 log lines:"
tail -8 /opt/grantglobe/stage3_full_run.log 2>/dev/null || echo "  (no full-run log yet)"
