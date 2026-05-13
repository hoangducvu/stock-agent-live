#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────
#  First-time server setup for 65.108.242.41 (Ubuntu)
#  Run as root: bash server-setup.sh
# ─────────────────────────────────────────────────────────
set -euo pipefail

echo "══════════════════════════════════════"
echo "  Server Setup — StockAgent Deploy"
echo "══════════════════════════════════════"

# ── 1. System updates ──────────────────────────────────
echo "[1/5] Updating system..."
apt update && apt upgrade -y

# ── 2. Install Docker ──────────────────────────────────
echo "[2/5] Installing Docker..."
if ! command -v docker &>/dev/null; then
    curl -fsSL https://get.docker.com | bash
    systemctl enable docker
    systemctl start docker
else
    echo "  Docker already installed."
fi

# ── 3. Install Docker Compose plugin ──────────────────
echo "[3/5] Installing Docker Compose..."
if ! docker compose version &>/dev/null; then
    apt install -y docker-compose-plugin
else
    echo "  Docker Compose already installed."
fi

# ── 4. Firewall ───────────────────────────────────────
echo "[4/5] Configuring firewall..."
apt install -y ufw
ufw default deny incoming
ufw default allow outgoing
ufw allow 22/tcp    # SSH
ufw allow 80/tcp    # HTTP (frontend)
ufw allow 443/tcp   # HTTPS (future)
ufw --force enable

# ── 5. Create deploy directory ────────────────────────
echo "[5/5] Creating app directory..."
mkdir -p /opt/stockbot
mkdir -p /opt/admin-portal

echo ""
echo "══════════════════════════════════════"
echo "  Setup complete!"
echo "  Docker: $(docker --version)"
echo "  Compose: $(docker compose version)"
echo "══════════════════════════════════════"
