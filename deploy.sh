#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  Deploy stock bot to Hetzner server
#  Run from Windows Git Bash / WSL / PowerShell
#  Usage: bash deploy.sh
# ─────────────────────────────────────────────────────────
set -euo pipefail

SERVER="root@65.108.242.41"
REMOTE_DIR="/opt/stockbot"
LOCAL_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "══════════════════════════════════════"
echo "  Deploying StockAgent to server"
echo "══════════════════════════════════════"

# ── 1. Sync files to server ───────────────────────────
echo "[1/3] Uploading files..."
rsync -avz --progress \
    --exclude 'node_modules' \
    --exclude 'frontend/dist' \
    --exclude '.git' \
    --exclude 'logs/*.log' \
    --exclude 'electron' \
    --exclude '__pycache__' \
    --exclude '.claude' \
    "$LOCAL_DIR/" "$SERVER:$REMOTE_DIR/"

# ── 2. Copy .env (only if not already on server) ─────
echo "[2/3] Checking .env..."
ssh "$SERVER" "test -f $REMOTE_DIR/.env" || {
    echo "  Uploading .env file..."
    scp "$LOCAL_DIR/.env" "$SERVER:$REMOTE_DIR/.env"
}

# ── 3. Build and start containers ────────────────────
echo "[3/3] Building & starting containers..."
ssh "$SERVER" "cd $REMOTE_DIR && docker compose down && docker compose up -d --build"

echo ""
echo "══════════════════════════════════════"
echo "  Deployed!"
echo "  Dashboard: http://65.108.242.41"
echo "  Bot logs:  ssh $SERVER 'docker logs -f stockbot'"
echo "══════════════════════════════════════"
