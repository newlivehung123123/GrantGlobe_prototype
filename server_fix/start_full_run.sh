#!/usr/bin/env bash
# GrantGlobe Stage 3 — reset the log and launch the full backfill.
# Run only after apply_fix.sh reports a passing smoke test.
set -euo pipefail

S3=/opt/grantglobe/Stage_3_LLM_extraction
cd "$S3"
set -a; source .env; set +a
export STAGE3_FORCE=1

echo "== Resetting extraction_log =="
echo "   (every prior row was processed on corrupted input — all must be redone)"
"$S3/.venv/bin/python" - <<'EOF'
from stage3.db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute(
    "UPDATE extraction_log SET status='pending', error_message=NULL, "
    "records_extracted=NULL "
    "WHERE status IN ('failed','processing','completed','skipped')"
)
print("rows reset:", cur.rowcount)
conn.commit()
cur.close()
conn.close()
EOF

echo "== Launching full extraction in background =="
nohup "$S3/.venv/bin/python" "$S3/run_full_extraction.py" \
    > /opt/grantglobe/stage3_full_run.log 2>&1 &
echo "PID: $!"
echo ""
echo "Monitor live:    tail -f /opt/grantglobe/stage3_full_run.log"
echo "Check progress:  bash /tmp/server_fix/check_status.sh"
echo ""
echo "When it finishes, restart the daily scheduler:"
echo "    systemctl start grantglobe-stage3"
