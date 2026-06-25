#!/usr/bin/env bash
# GrantGlobe Stage 3 — fix #2: meta_not_found mass-failure.
#
# Root cause: _build_meta_index(raw_cache_dir, run_date) only indexed meta
# files matching the CURRENT cycle's run_date. Rows left pending from a prior
# cycle (registered under an earlier crawl_date) were claimed anyway, but
# their url_hash was absent from that index, so every one of them failed with
# "meta_not_found". This affected ~1800 rows (everything carried over from
# the 2026-05-31 batch into the 2026-06-01 cycle) — not just the first 150.
#
# Fix: _build_meta_index now indexes ALL meta files keyed by
# (url_hash, crawl_date), and each claimed row is looked up by its OWN
# crawl_date, not the cycle's run_date.
#
# This script: stops the in-progress run, installs the corrected
# batch_processor.py, resets the meta_not_found rows (and only those) back to
# pending, and resumes the backfill. Nothing already completed is touched.
set -euo pipefail

S3=/opt/grantglobe/Stage_3_LLM_extraction
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1/5  Stopping the in-progress backfill =="
pkill -f "run_full_extraction" 2>/dev/null || true
sleep 2

echo "== 2/5  Installing corrected batch_processor.py =="
install -m 644 "$HERE/batch_processor.py" "$S3/stage3/batch_processor.py"

echo "== 3/5  Syntax check =="
"$S3/.venv/bin/python" -m py_compile "$S3/stage3/batch_processor.py"
echo "    syntax OK"

echo "== 4/5  Resetting meta_not_found rows to pending =="
cd "$S3"
set -a; source .env; set +a
"$S3/.venv/bin/python" - <<'EOF'
from stage3.db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute(
    "UPDATE extraction_log SET status='pending', error_message=NULL "
    "WHERE status='failed' AND error_message='meta_not_found'"
)
print("rows reset:", cur.rowcount)
conn.commit()
cur.close()
conn.close()
EOF

echo "== 5/5  Resuming the backfill in background =="
export STAGE3_FORCE=1
nohup "$S3/.venv/bin/python" "$S3/run_full_extraction.py" \
    >> /opt/grantglobe/stage3_full_run.log 2>&1 &
echo "PID: $!"
echo ""
echo "Monitor:  bash /tmp/server_fix/check_status.sh"
