#!/usr/bin/env bash
# GrantGlobe — VPS deployment script
# Target: Hetzner CX22, Ubuntu 22.04 LTS
#
# Run once as root immediately after provisioning the server:
#   ssh root@<your-server-ip>
#   curl -fsSL https://raw.githubusercontent.com/newlivehung123123/GrantGlobe_prototype/main/deploy_vps.sh | bash
#
# Or copy this file to the server and run:
#   chmod +x deploy_vps.sh && sudo bash deploy_vps.sh
#
# After the script completes, fill in the two .env files:
#   /opt/grantglobe/Stage_2_crawler/.env
#   /opt/grantglobe/Stage_3_LLM_extraction/.env
# Then run:
#   sudo systemctl start grantglobe-stage2 grantglobe-stage3

set -euo pipefail

REPO_URL="https://github.com/newlivehung123123/GrantGlobe_prototype.git"
APP_DIR="/opt/grantglobe"
APP_USER="grantglobe"
PYTHON="python3"

echo "==> [1/9] System update"
apt-get update -y
apt-get upgrade -y

echo "==> [2/9] Install system packages"
apt-get install -y \
    git \
    python3 \
    python3-venv \
    python3-pip \
    tesseract-ocr \
    tesseract-ocr-eng \
    tesseract-ocr-fra \
    tesseract-ocr-spa \
    tesseract-ocr-ara \
    poppler-utils \
    libnss3 \
    libatk-bridge2.0-0 \
    libcups2 \
    libxkbcommon0 \
    libxdamage1 \
    libgbm1 \
    libasound2t64 \
    libpangocairo-1.0-0 \
    libgtk-3-0

echo "==> [3/9] Create application user"
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$APP_USER"
fi

echo "==> [4/9] Clone repository"
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR" && git pull
else
    git clone "$REPO_URL" "$APP_DIR"
fi
chown -R "$APP_USER:$APP_USER" "$APP_DIR"

echo "==> [5/9] Install Stage 2 Python dependencies"
sudo -u "$APP_USER" bash <<'EOF'
    cd /opt/grantglobe/Stage_2_crawler
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
    .venv/bin/playwright install chromium --with-deps
EOF

echo "==> [6/9] Install Stage 3 Python dependencies"
sudo -u "$APP_USER" bash <<'EOF'
    cd /opt/grantglobe/Stage_3_LLM_extraction
    python3 -m venv .venv
    .venv/bin/pip install --upgrade pip
    .venv/bin/pip install -r requirements.txt
EOF

echo "==> [7/9] Write .env templates (fill in values before starting services)"
STAGE2_ENV="/opt/grantglobe/Stage_2_crawler/.env"
STAGE3_ENV="/opt/grantglobe/Stage_3_LLM_extraction/.env"

if [ ! -f "$STAGE2_ENV" ]; then
    cat > "$STAGE2_ENV" <<'ENVEOF'
# Stage 2 environment — fill in all values before starting the service
COOKIE_ENCRYPTION_KEY=

# Proxy (leave blank to disable)
PROXY_HOST=
PROXY_PORT=
PROXY_USERNAME=
PROXY_PASSWORD=

# Alert email (leave ALERT_EMAIL_HOST blank to disable email alerts)
ALERT_EMAIL_HOST=
ALERT_EMAIL_PORT=587
ALERT_EMAIL_USER=
ALERT_EMAIL_PASSWORD=
ALERT_EMAIL_FROM=
ALERT_EMAIL_TO=

# Alert webhook (leave blank to disable)
ALERT_WEBHOOK_URL=
ENVEOF
fi

if [ ! -f "$STAGE3_ENV" ]; then
    cat > "$STAGE3_ENV" <<'ENVEOF'
# Stage 3 environment — fill in all values before starting the service
GEMINI_API_KEY=

DATABASE_URL=postgresql://neondb_owner:npg_k3SRDiyAT2JL@ep-round-flower-apvinffh.c-7.us-east-1.aws.neon.tech/neondb?sslmode=require

# Path to Stage 2 raw_cache (relative to Stage_3_LLM_extraction dir,
# or use an absolute path)
RAW_CACHE_DIR=/opt/grantglobe/Stage_2_crawler/raw_cache

STAGE3_OUTPUT_DIR=/opt/grantglobe/Stage_3_LLM_extraction/stage3_output
STAGE3_BATCH_SIZE=2000
STAGE3_MAX_RETRIES=3
STAGE3_REVIEW_CONFIDENCE_THRESHOLD=low
STAGE3_MAX_COST=
ENVEOF
fi

chown "$APP_USER:$APP_USER" "$STAGE2_ENV" "$STAGE3_ENV"
chmod 600 "$STAGE2_ENV" "$STAGE3_ENV"

echo "==> [8/9] Install systemd service files"
cp "$APP_DIR/grantglobe-stage2.service" /etc/systemd/system/grantglobe-stage2.service
cp "$APP_DIR/grantglobe-stage3.service" /etc/systemd/system/grantglobe-stage3.service
systemctl daemon-reload
systemctl enable grantglobe-stage2 grantglobe-stage3

echo "==> [9/9] Done — next steps:"
echo ""
echo "  1. Generate a Fernet key for COOKIE_ENCRYPTION_KEY:"
echo "     sudo -u grantglobe /opt/grantglobe/Stage_2_crawler/.venv/bin/python -c \\"
echo "       \"from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())\""
echo ""
echo "  2. Fill in /opt/grantglobe/Stage_2_crawler/.env"
echo "     (paste the Fernet key into COOKIE_ENCRYPTION_KEY)"
echo ""
echo "  3. Fill in /opt/grantglobe/Stage_3_LLM_extraction/.env"
echo "     (paste your GEMINI_API_KEY)"
echo ""
echo "  4. Start both services:"
echo "     sudo systemctl start grantglobe-stage2 grantglobe-stage3"
echo ""
echo "  5. Check service health:"
echo "     sudo journalctl -u grantglobe-stage2 -f"
echo "     sudo journalctl -u grantglobe-stage3 -f"
echo ""
echo "  6. Trigger a manual first run to verify the pipeline:"
echo "     sudo systemctl kill --signal=SIGUSR1 grantglobe-stage2"
echo "  (Or wait for the scheduled Sunday 02:00 UTC run.)"
