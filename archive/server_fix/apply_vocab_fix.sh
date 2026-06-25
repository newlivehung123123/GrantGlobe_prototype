#!/usr/bin/env bash
# GrantGlobe Stage 3 — fix #3: controlled-vocabulary review-queue gate.
#
# normalise_controlled_vocab() required an exact (case-insensitive) string
# match against the fixed vocab lists, with no fuzzy matching — unlike
# funder/country normalisation, which already used fuzz.ratio() at 88-90.
# As a result 94.8% of extracted grants were flagged "Others" on at least one
# of thematic_sectors / geographic_focus_regions / individual_eligibility and
# routed to manual review, even when the LLM's wording was a clear synonym
# ("Researchers" vs "Senior / Established Researcher or Professional",
# "Education" vs "Education and Training", em-dash vs hyphen variants of
# vocab entries that should have matched exactly).
#
# This script:
#   1. Stops the in-progress backfill (any orphaned 'processing' rows are
#      reset, same as reset_orphans_and_resume.sh).
#   2. Installs the corrected normaliser.py (fuzzy matching at >=85 for
#      controlled vocab + status) and extractor.py (adds a controlled-
#      vocabulary hint to the Gemini prompt for future extractions).
#   3. Re-normalises the 2270 already-extracted, still-pending review-queue
#      grants against the new logic — no new Gemini calls, no cost. Grants
#      an operator has already approved/rejected are left untouched.
#   4. Resumes the backfill for any pages still pending.
set -euo pipefail

S3=/opt/grantglobe/Stage_3_LLM_extraction
HERE="$(cd "$(dirname "$0")" && pwd)"

echo "== 1/5  Stopping the in-progress backfill =="
pkill -f "run_full_extraction" 2>/dev/null || true
sleep 2

echo "== 2/5  Installing corrected normaliser.py and extractor.py =="
install -m 644 "$HERE/normaliser.py" "$S3/stage3/normaliser.py"
install -m 644 "$HERE/extractor.py"  "$S3/stage3/extractor.py"

echo "== 3/5  Syntax check =="
"$S3/.venv/bin/python" -m py_compile \
    "$S3/stage3/normaliser.py" "$S3/stage3/extractor.py"
echo "    syntax OK"

cd "$S3"
set -a; source .env; set +a

echo "== 4/5  Re-normalising the existing review queue =="
"$S3/.venv/bin/python" -c "import runpy; runpy.run_path('$HERE/renormalise_review_queue.py', run_name='__main__')"

echo "== 5/5  Resetting any orphaned processing rows and resuming =="
"$S3/.venv/bin/python" - <<'EOF'
from stage3.db import get_connection
conn = get_connection()
cur = conn.cursor()
cur.execute("UPDATE extraction_log SET status='pending', error_message=NULL WHERE status='processing'")
print("rows reset:", cur.rowcount)
conn.commit()
cur.close()
conn.close()
EOF

export STAGE3_FORCE=1
nohup "$S3/.venv/bin/python" "$S3/run_full_extraction.py" \
    >> /opt/grantglobe/stage3_full_run.log 2>&1 &
echo "PID: $!"
echo ""
echo "Monitor:  bash /tmp/server_fix/check_status.sh"
