# ─────────────────────────────────────────────────────────
#  Deploy stock bot — PowerShell version (native Windows)
#  Usage: .\deploy.ps1
# ─────────────────────────────────────────────────────────

$SERVER = "root@65.108.242.41"
$REMOTE_DIR = "/opt/stockbot"
$LOCAL_DIR = Split-Path -Parent $MyInvocation.MyCommand.Path

Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan
Write-Host "  Deploying StockAgent to server" -ForegroundColor Cyan
Write-Host "═══════════════════════════════════════" -ForegroundColor Cyan

# 1. Upload files via SCP (recursive)
Write-Host "[1/3] Uploading files..." -ForegroundColor Yellow
scp -r "$LOCAL_DIR\Dockerfile.bot" "$LOCAL_DIR\Dockerfile.backend" "$LOCAL_DIR\Dockerfile.frontend" `
    "$LOCAL_DIR\docker-compose.yml" "$LOCAL_DIR\.dockerignore" `
    "$LOCAL_DIR\nginx" `
    "$LOCAL_DIR\requirements.txt" "$LOCAL_DIR\backend" "$LOCAL_DIR\frontend" `
    "$LOCAL_DIR\main.py" "$LOCAL_DIR\config.py" "$LOCAL_DIR\env_loader.py" `
    "$LOCAL_DIR\logger_setup.py" "$LOCAL_DIR\account_manager.py" `
    "$LOCAL_DIR\risk_manager.py" "$LOCAL_DIR\order_manager.py" `
    "$LOCAL_DIR\data_feed.py" "$LOCAL_DIR\indicators.py" `
    "$LOCAL_DIR\explainer.py" "$LOCAL_DIR\slack_controller.py" `
    "$LOCAL_DIR\strategy_ema_vwap.py" "$LOCAL_DIR\strategy_orb.py" `
    "$LOCAL_DIR\strategy_rsi.py" "$LOCAL_DIR\utils.py" `
    "$LOCAL_DIR\data" `
    "${SERVER}:${REMOTE_DIR}/"

# 2. Upload .env
Write-Host "[2/3] Uploading .env..." -ForegroundColor Yellow
scp "$LOCAL_DIR\.env" "${SERVER}:${REMOTE_DIR}/.env"

# 3. Build & start on server
Write-Host "[3/3] Building & starting..." -ForegroundColor Yellow
ssh $SERVER "cd $REMOTE_DIR && docker compose down && docker compose up -d --build"

Write-Host ""
Write-Host "═══════════════════════════════════════" -ForegroundColor Green
Write-Host "  Deployed!" -ForegroundColor Green
Write-Host "  Dashboard: http://65.108.242.41" -ForegroundColor Green
Write-Host "  Bot logs: ssh $SERVER 'docker logs -f stockbot'" -ForegroundColor Green
Write-Host "═══════════════════════════════════════" -ForegroundColor Green
