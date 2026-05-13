# StockAgent — Demo Setup Guide

## What's included
- **Onboarding** — Alpaca API key entry, paper/live mode selection, account validation
- **Dashboard** — Portfolio value, P&L chart, open positions, recent orders, watchlist
- **Stocks** — Full watchlist with live prices, % change, volume, your positions
- **Strategy Builder** — Browse 3 built-in strategies (EMA/VWAP, ORB, RSI), custom strategy input, bot start/stop, live log viewer

---

## Requirements
- Python 3.10+
- Node.js 18+
- An [Alpaca account](https://app.alpaca.markets) (free — paper trading needs no funding)

---

## Quick Start (Web — PC & Mobile)

### Windows
```
double-click start.bat
```
Then open **http://localhost:5173** in any browser.
Works on phone/tablet on the same Wi-Fi — use your PC's IP instead of localhost.

### Mac / Linux
```bash
chmod +x start.sh
./start.sh
```

---

## First Run
1. App opens at **http://localhost:5173**
2. Click **Get Started**
3. Paste your Alpaca **API Key ID** and **Secret Key**
   - Get them from: https://app.alpaca.markets/paper/dashboard/overview
4. Choose **Paper Trading** (recommended for demo)
5. Click **Validate & Connect** — your live account data loads instantly

---

## Desktop App (Electron)

Run as a native desktop window:
```bash
cd path/to/stock-agent-live
npm install          # installs Electron + concurrently
npm run electron:dev # opens native window + starts both servers
```

Build installers:
```bash
npm run build:win    # → dist-electron/*.exe  (Windows)
npm run build:mac    # → dist-electron/*.dmg  (macOS)
npm run build:linux  # → dist-electron/*.AppImage (Linux)
```

---

## Architecture

```
stock-agent-live/
├── backend/          ← FastAPI proxy (port 8000)
│   └── main.py       ← Alpaca REST proxy, bot control, strategy list
├── frontend/         ← React + Vite UI (port 5173)
│   └── src/
│       ├── pages/    ← Onboarding, Dashboard, Stocks, Strategy
│       ├── components/  ← Sidebar
│       ├── contexts/    ← AuthContext (API keys)
│       └── api/         ← Alpaca API calls
├── electron/         ← Desktop wrapper
│   └── main.js
├── *.py              ← Existing trading bot strategies
├── start.bat         ← Windows launcher
└── start.sh          ← Mac/Linux launcher
```

---

## Strategies included
| Name | Risk | Timeframe | Description |
|------|------|-----------|-------------|
| EMA + VWAP Momentum | Medium | 5m | Fast/slow EMA cross above VWAP |
| Opening Range Breakout | High | 15m | ATR-based ORB breakout |
| RSI Mean Reversion | Low | 1h | RSI oversold/overbought |
| Custom | Variable | Any | Describe in plain English |

---

## Mobile
The web app is fully responsive. On the same Wi-Fi network:
1. Find your PC's IP: `ipconfig` (Windows) or `ifconfig` (Mac/Linux)
2. Open `http://YOUR_PC_IP:5173` on your phone
3. Add to home screen for app-like experience (PWA)

---

## Notes
- API keys stored **locally only** (browser localStorage) — never sent anywhere except directly to Alpaca
- Paper trading = zero financial risk, real market data
- Bot start/stop controls the existing Python trading engine in the same folder
