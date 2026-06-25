#!/usr/bin/env bash
# GrantGlobe Stage 3 fix — installation and smoke test.
# Run on the server as root:  bash /tmp/server_fix/apply_fix.sh
set -euo pipefail

S3=/opt/grantglobe/Stage_3_LLM_extraction
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1/7  Stopping any running extraction =="
pkill -f "run_extraction_cycle" 2>/dev/null || true
pkill -f "run_full_extraction" 2>/dev/null || true
systemctl stop grantglobe-stage3 2>/dev/null || true

echo "== 2/7  Backing up current stage3 code =="
BACKUP="$S3/stage3.bak.$(date +%Y%m%d%H%M%S)"
cp -a "$S3/stage3" "$BACKUP"
echo "    backup at: $BACKUP"

echo "== 3/7  Installing fixed files =="
install -m 644 "$HERE/batch_processor.py"      "$S3/stage3/batch_processor.py"
install -m 644 "$HERE/extractor.py"            "$S3/stage3/extractor.py"
install -m 644 "$HERE/scheduler.py"            "$S3/stage3/scheduler.py"
install -m 644 "$HERE/diagnose_extraction.py"  "$S3/diagnose_extraction.py"
install -m 644 "$HERE/run_full_extraction.py"  "$S3/run_full_extraction.py"

echo "== 4/7  Ensuring google-genai is installed in the venv =="
"$S3/.venv/bin/pip" install --quiet google-genai

echo "== 5/7  Making STAGE3_FORCE permanent for the service =="
mkdir -p /etc/systemd/system/grantglobe-stage3.service.d
cat > /etc/systemd/system/grantglobe-stage3.service.d/override.conf <<'EOF'
[Service]
Environment="STAGE3_FORCE=1"
EOF
systemctl daemon-reload

echo "== 6/7  Syntax check =="
"$S3/.venv/bin/python" -m py_compile \
    "$S3/stage3/batch_processor.py" \
    "$S3/stage3/extractor.py" \
    "$S3/stage3/scheduler.py"
echo "    syntax OK"

echo "== 7/7  Smoke test: 8 pages through the fixed pipeline (no DB writes) =="
cd "$S3"
set -a; source .env; set +a
if ! "$S3/.venv/bin/python" "$S3/diagnose_extraction.py"; then
    echo ""
    echo "SMOKE TEST FAILED. Do not start the full run. Share the output above."
    exit 1
fi

echo ""
echo "Smoke test passed. Start the full backfill with:"
echo "    bash $HERE/start_full_run.sh"
