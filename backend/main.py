"""
Stock Agent — FastAPI Backend Proxy
Proxies Alpaca REST API, manages bot lifecycle, serves strategy list.
"""

from fastapi import FastAPI, HTTPException, Header
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import httpx
import asyncio
import subprocess
import os
import sys
import json
from pathlib import Path

app = FastAPI(title="StockAgent API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── In-memory bot state ────────────────────────────────────────────────────────
bot_processes: dict[str, subprocess.Popen] = {}   # strategy_id → process
bot_log_buffers: dict[str, list[str]] = {}         # strategy_id → log lines
stored_creds: dict = {}                            # credentials from last bot start

BOT_STATE_FILE = Path(__file__).parent.parent / "data" / "bot_state.json"

def _read_bot_state() -> dict:
    try:
        return json.loads(BOT_STATE_FILE.read_text())
    except Exception:
        return {}

PAPER_BASE = "https://paper-api.alpaca.markets"
LIVE_BASE  = "https://api.alpaca.markets"
DATA_BASE  = "https://data.alpaca.markets"


def alpaca_headers(api_key: str, secret_key: str) -> dict:
    return {
        "APCA-API-KEY-ID": api_key,
        "APCA-API-SECRET-KEY": secret_key,
        "Accept": "application/json",
    }


def base_url(paper: bool) -> str:
    return PAPER_BASE if paper else LIVE_BASE


# ── Models ────────────────────────────────────────────────────────────────────
class Credentials(BaseModel):
    api_key: str
    secret_key: str
    paper: bool = True


class BotStartRequest(BaseModel):
    api_key: str
    secret_key: str
    paper: bool = True
    strategy: str = "ema_vwap"


class TestOrderRequest(BaseModel):
    symbol: str = "AAPL"
    qty: float = 1
    side: str = "buy"


# ── Auth / Account ─────────────────────────────────────────────────────────────
@app.post("/api/validate")
async def validate_credentials(creds: Credentials):
    url = f"{base_url(creds.paper)}/v2/account"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=alpaca_headers(creds.api_key, creds.secret_key), timeout=10)
            if r.status_code == 403:
                raise HTTPException(status_code=403, detail="Invalid API credentials")
            r.raise_for_status()
            data = r.json()
            return {
                "valid": True,
                "account_number": data.get("account_number"),
                "status": data.get("status"),
                "equity": data.get("equity"),
                "cash": data.get("cash"),
                "buying_power": data.get("buying_power"),
                "portfolio_value": data.get("portfolio_value"),
                "paper": creds.paper,
            }
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=str(e))


@app.get("/api/account")
async def get_account(
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
    x_paper: str = Header(default="true"),
):
    paper = x_paper.lower() == "true"
    url = f"{base_url(paper)}/v2/account"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=alpaca_headers(x_api_key, x_secret_key), timeout=10)
        r.raise_for_status()
        return r.json()


# ── Positions ──────────────────────────────────────────────────────────────────
@app.get("/api/positions")
async def get_positions(
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
    x_paper: str = Header(default="true"),
):
    paper = x_paper.lower() == "true"
    url = f"{base_url(paper)}/v2/positions"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=alpaca_headers(x_api_key, x_secret_key), timeout=10)
        r.raise_for_status()
        return r.json()


# ── Orders ─────────────────────────────────────────────────────────────────────
@app.get("/api/orders")
async def get_orders(
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
    x_paper: str = Header(default="true"),
    status: str = "all",
    limit: int = 50,
):
    paper = x_paper.lower() == "true"
    url = f"{base_url(paper)}/v2/orders"
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url,
            headers=alpaca_headers(x_api_key, x_secret_key),
            params={"status": status, "limit": limit},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()


class OrderRequest(BaseModel):
    symbol: str
    qty: float
    side: str          # "buy" or "sell"
    type: str = "market"
    time_in_force: str = "day"
    limit_price: Optional[float] = None


@app.post("/api/orders")
async def place_order(
    order: OrderRequest,
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
    x_paper: str = Header(default="true"),
):
    paper = x_paper.lower() == "true"
    url = f"{base_url(paper)}/v2/orders"
    payload = {
        "symbol": order.symbol,
        "qty": str(order.qty),
        "side": order.side,
        "type": order.type,
        "time_in_force": order.time_in_force,
    }
    if order.limit_price is not None:
        payload["limit_price"] = str(order.limit_price)
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            headers={**alpaca_headers(x_api_key, x_secret_key), "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if not r.is_success:
            err = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            raise HTTPException(status_code=r.status_code, detail=err.get("message", r.text))
        return r.json()


@app.delete("/api/orders/{order_id}")
async def cancel_order(
    order_id: str,
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
    x_paper: str = Header(default="true"),
):
    paper = x_paper.lower() == "true"
    url = f"{base_url(paper)}/v2/orders/{order_id}"
    async with httpx.AsyncClient() as client:
        r = await client.delete(url, headers=alpaca_headers(x_api_key, x_secret_key), timeout=10)
        if r.status_code == 204:
            return {"status": "cancelled"}
        r.raise_for_status()
        return r.json()


# ── Portfolio History ──────────────────────────────────────────────────────────
@app.get("/api/portfolio/history")
async def get_portfolio_history(
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
    x_paper: str = Header(default="true"),
    period: str = "1W",
    timeframe: str = "1D",
):
    paper = x_paper.lower() == "true"
    url = f"{base_url(paper)}/v2/account/portfolio/history"
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url,
            headers=alpaca_headers(x_api_key, x_secret_key),
            params={"period": period, "timeframe": timeframe},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()


# ── Market Data ────────────────────────────────────────────────────────────────
@app.get("/api/quotes")
async def get_quotes(
    symbols: str,
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
):
    url = f"{DATA_BASE}/v2/stocks/snapshots"
    async with httpx.AsyncClient() as client:
        r = await client.get(
            url,
            headers=alpaca_headers(x_api_key, x_secret_key),
            params={"symbols": symbols, "feed": "iex"},
            timeout=10,
        )
        r.raise_for_status()
        return r.json()


# ── Strategies ─────────────────────────────────────────────────────────────────
STRATEGIES = [
    {
        "id": "ema_vwap",
        "name": "EMA + VWAP Momentum",
        "description": "Buys when fast EMA crosses above slow EMA while price is above VWAP. Intraday 5-min bars.",
        "risk": "Medium",
        "timeframe": "5m",
        "winRate": "64%",
        "avgReturn": "+12.4%",
        "tags": ["momentum", "intraday", "trend"],
        "params": {"fast_ema": 9, "slow_ema": 21, "trend_ema": 55, "stop_atr": 1.5, "tp_atr": 2.5},
        "file": "strategy_ema_vwap.py",
    },
    {
        "id": "orb",
        "name": "Opening Range Breakout",
        "description": "Trades breakouts above/below the first 15-minute range with ATR-based stops.",
        "risk": "High",
        "timeframe": "15m",
        "winRate": "52%",
        "avgReturn": "+18.7%",
        "tags": ["breakout", "morning", "volatility"],
        "params": {"orb_minutes": 15, "stop_atr": 1.0, "tp_atr": 2.0},
        "file": "strategy_orb.py",
    },
    {
        "id": "rsi",
        "name": "RSI Mean Reversion",
        "description": "Buys oversold dips (RSI < 30) and sells overbought rallies (RSI > 70) with tight risk controls.",
        "risk": "Low",
        "timeframe": "1h",
        "winRate": "71%",
        "avgReturn": "+8.2%",
        "tags": ["mean-reversion", "oscillator", "swing"],
        "params": {"rsi_period": 14, "oversold": 30, "overbought": 70},
        "file": "strategy_rsi.py",
    },
    {
        "id": "custom",
        "name": "Custom Strategy",
        "description": "Describe your own strategy in plain English and the AI will configure parameters for you.",
        "risk": "Variable",
        "timeframe": "Any",
        "winRate": "—",
        "avgReturn": "—",
        "tags": ["ai", "custom", "flexible"],
        "params": {},
        "file": None,
    },
]


@app.get("/api/strategies")
async def list_strategies():
    return STRATEGIES


# ── Bot Control ────────────────────────────────────────────────────────────────
STRATEGY_META = {
    "ema_vwap": {"name": "EMA + VWAP Momentum", "stocks": ["AAPL", "NVDA", "MSFT", "TSLA"]},
    "orb":      {"name": "Opening Range Breakout", "stocks": ["TSLA", "AMD", "META", "PLTR"]},
    "rsi":      {"name": "RSI Mean Reversion", "stocks": ["MSFT", "GOOGL", "AMZN", "SPY"]},
}


def _write_bot_state(state: dict):
    try:
        BOT_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        BOT_STATE_FILE.write_text(json.dumps(state))
    except Exception:
        pass


def _bot_alive(strategy_id: str) -> bool:
    p = bot_processes.get(strategy_id)
    return p is not None and p.poll() is None


def _drain_logs(strategy_id: str):
    p = bot_processes.get(strategy_id)
    if not p or not p.stdout:
        return
    buf = bot_log_buffers.setdefault(strategy_id, [])
    import select, os as _os
    try:
        while select.select([p.stdout], [], [], 0)[0]:
            line = _os.read(p.stdout.fileno(), 4096).decode(errors="replace")
            if not line:
                break
            for ln in line.splitlines():
                buf.append(ln)
        bot_log_buffers[strategy_id] = buf[-200:]
    except Exception:
        pass


@app.get("/api/bot/status")
async def bot_status():
    # Drain logs for all running bots
    for sid in list(bot_processes.keys()):
        _drain_logs(sid)
    # Build per-strategy status map
    statuses = {
        sid: {
            "running": _bot_alive(sid),
            "logs": bot_log_buffers.get(sid, [])[-50:],
        }
        for sid in bot_processes
    }
    any_running = any(v["running"] for v in statuses.values())
    active_ids = [sid for sid, v in statuses.items() if v["running"]]
    return {
        "running": any_running,
        "strategy": active_ids[0] if len(active_ids) == 1 else (active_ids or None),
        "strategies": statuses,
        "logs": bot_log_buffers.get(active_ids[0], [])[-50:] if active_ids else [],
    }


@app.post("/api/bot/start")
async def bot_start(req: BotStartRequest):
    global stored_creds

    # If this exact strategy is already running, no-op
    if _bot_alive(req.strategy):
        return {"status": "already_running", "strategy": req.strategy}

    stored_creds = {"api_key": req.api_key, "secret_key": req.secret_key, "paper": req.paper}
    bot_log_buffers[req.strategy] = []

    env = {
        **os.environ,
        "ALPACA_API_KEY": req.api_key,
        "ALPACA_SECRET_KEY": req.secret_key,
        "ALPACA_PAPER": "true" if req.paper else "false",
        "STRATEGY": req.strategy,
    }

    # Resolve bot script — check env override first, then common locations
    _candidates = [
        Path(os.environ.get("BOT_SCRIPT", "")),
        Path(__file__).parent.parent / "main.py",
        Path(__file__).parent / "main.py",
        Path("/opt/stock-agent/main.py"),
    ]
    bot_script = next((p for p in _candidates if p.name and p.exists()), None)
    if bot_script is None:
        raise HTTPException(status_code=500, detail=f"Bot script not found. Set BOT_SCRIPT env var or place main.py alongside backend/.")

    try:
        proc = subprocess.Popen(
            [sys.executable, str(bot_script)],
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env=env,
            bufsize=1,
        )
        bot_processes[req.strategy] = proc
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to start bot: {e}")

    _write_bot_state({"active_strategies": list(bot_processes.keys()), "paper": req.paper})
    return {"status": "started", "strategy": req.strategy, "pid": proc.pid}


@app.post("/api/bot/stop")
async def bot_stop(strategy: Optional[str] = None):
    global bot_processes

    # Stop a specific strategy or all if none specified
    targets = [strategy] if strategy and strategy in bot_processes else list(bot_processes.keys())

    for sid in targets:
        p = bot_processes.get(sid)
        if p and p.poll() is None:
            p.terminate()
            await asyncio.sleep(0.5)
            if p.poll() is None:
                p.kill()
        bot_processes.pop(sid, None)

    _write_bot_state({"active_strategies": list(bot_processes.keys())})
    return {"status": "stopped", "stopped": targets}


@app.get("/api/bots")
async def list_bots():
    state = _read_bot_state()
    trades_today = state.get("trades_today", [])

    rows = []
    for i, (sid, meta) in enumerate(STRATEGY_META.items()):
        strat_trades = [t for t in trades_today if t.get("strategy") == sid]
        pnl = sum(t.get("pnl", 0) for t in strat_trades)
        win_trades = [t for t in strat_trades if t.get("pnl", 0) > 0]
        win_rate = round(len(win_trades) / len(strat_trades) * 100) if strat_trades else 0
        rows.append({
            "id": i + 1,
            "strategy_id": sid,
            "name": meta["name"],
            "status": "active" if _bot_alive(sid) else "stopped",
            "stocks": meta["stocks"],
            "trades": len(strat_trades),
            "winRate": win_rate,
            "pnl": round(pnl, 2),
        })
    return rows


# ── Test Order ─────────────────────────────────────────────────────────────────
@app.post("/api/bot/test-order")
async def test_order(
    req: TestOrderRequest,
    x_api_key: str = Header(default=""),
    x_secret_key: str = Header(default=""),
    x_paper: str = Header(default="true"),
):
    api_key    = x_api_key    or stored_creds.get("api_key", "")
    secret_key = x_secret_key or stored_creds.get("secret_key", "")
    paper      = (x_paper.lower() == "true") if x_api_key else stored_creds.get("paper", True)

    if not api_key or not secret_key:
        raise HTTPException(status_code=400, detail="No credentials. Start the bot first or pass headers.")

    url = f"{base_url(paper)}/v2/orders"
    payload = {
        "symbol": req.symbol.upper(),
        "qty": str(req.qty),
        "side": req.side,
        "type": "market",
        "time_in_force": "day",
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(
            url,
            headers={**alpaca_headers(api_key, secret_key), "Content-Type": "application/json"},
            json=payload,
            timeout=10,
        )
        if not r.is_success:
            err = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            raise HTTPException(status_code=r.status_code, detail=err.get("message", r.text))
        result = r.json()
        return {
            "order_id": result.get("id"),
            "symbol": result.get("symbol"),
            "side": result.get("side"),
            "qty": result.get("qty"),
            "status":   result.get("status"),
            "submitted_at": result.get("submitted_at"),
            "paper": paper,
        }


@app.get("/api/health")
async def health():
    return {"status": "ok", "bot_running": any(_bot_alive(s) for s in bot_processes), "version": "1.0.0"}
