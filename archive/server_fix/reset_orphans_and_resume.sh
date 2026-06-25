#!/usr/bin/env bash
# Reset rows orphaned in 'processing' by a previous pkill, then resume.
set -euo pipefail

S3=/opt/grantglobe/Stage_3_LLM_extraction
cd "$S3"
set -a; source .env; set +a

echo "== Resetting orphaned processing rows =="
"$S3/.venv/bin/python" - <<'EOF'
from stage3.db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute(
    "UPDATE extraction_log SET status='pending', error_message=NULL "
    "WHERE status='processing'"
)
print("rows reset:", cur.rowcount)
conn.commit()
cur.close()
conn.close()
EOF

echo "== Resuming the backfill in background =="
export STAGE3_FORCE=1
nohup "$S3/.venv/bin/python" "$S3/run_full_extraction.py" \
    >> /opt/grantglobe/stage3_full_run.log 2>&1 &
echo "PID: $!"
echo ""
echo "Monitor:  bash /tmp/server_fix/check_status.sh"
