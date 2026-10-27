"""
Stock Agent — FastAPI Backend Proxy
Proxies Alpaca REST API, manages bot lifecycle, serves strategy list.
"""

from fastapi import FastAPI, HTTPException, Header, Request
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import Optional, Literal
import httpx
import asyncio
import subprocess
import os
import sys
import json
from pathlib import Path
from bot_runtime import BotRuntime
from contextlib import asynccontextmanager

from research.supervisor import ResearchSupervisor
research_supervisor = ResearchSupervisor()

runtime = BotRuntime(Path(__file__).parent.parent / "logs")

@asynccontextmanager
async def lifespan(app):
    research_supervisor.start()
    try:
        yield
    finally:
        await asyncio.to_thread(runtime.stop)
        await asyncio.to_thread(research_supervisor.stop)

app = FastAPI(title="StockAgent API", version="1.0.0", lifespan=lifespan)

@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Never echo request input: validation may involve broker secrets.
    return JSONResponse(status_code=422, content={'detail': [
        {'loc': list(e['loc']), 'msg': e['msg'], 'type': e['type']} for e in exc.errors()
    ]})

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://nexlara.eu", "http://127.0.0.1:8080", "http://localhost:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.middleware("http")
async def check_origin(request: Request, call_next):
    origin = request.headers.get("origin")
    allowed = {"https://nexlara.eu", "http://127.0.0.1:8080", "http://localhost:8080"}
    if request.method not in {"GET", "HEAD", "OPTIONS"} and ((origin and origin not in allowed) or request.headers.get("sec-fetch-site") == "cross-site"):
        return JSONResponse(status_code=403, content={"detail": "Untrusted request origin"})
    if request.url.path.startswith('/api/') and (request.headers.get('x-paper', 'true').lower() != 'true'):
        return JSONResponse(status_code=403, content={'detail': 'Live trading is disabled in this paper release.'})
    if request.method not in {'GET', 'HEAD', 'OPTIONS'} and (request.url.path.startswith('/api/orders') or request.url.path in {'/api/bot/start', '/api/bot/stop', '/api/bot/test-order'}):
        return JSONResponse(status_code=410, content={'detail': 'Use the saved-settings dashboard controls at /api/workspace/. Legacy trading controls are disabled.'})
    return await call_next(request)


# ── In-memory bot state ────────────────────────────────────────────────────────
bot_processes = runtime.processes   # strategy_id → process


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
    api_key: str = Field(min_length=1, max_length=256)
    secret_key: str = Field(min_length=1, max_length=256)
    paper: bool = True


class BotStartRequest(BaseModel):
    api_key: str = Field(min_length=1, max_length=256)
    secret_key: str = Field(min_length=1, max_length=256)
    paper: bool = True
    strategy: Literal["ema_vwap", "orb", "rsi"] = "ema_vwap"


class TestOrderRequest(BaseModel):
    symbol: str = "AAPL"
    qty: float = Field(default=1, gt=0, allow_inf_nan=False)
    side: Literal["buy", "sell"] = "buy"


# ── Auth / Account ─────────────────────────────────────────────────────────────
@app.post("/api/validate")
async def validate_credentials(creds: Credentials):
    url = f"{base_url(creds.paper)}/v2/account"
    async with httpx.AsyncClient() as client:
        try:
            r = await client.get(url, headers=alpaca_headers(creds.api_key, creds.secret_key), timeout=10)
            if r.status_code in (401, 403):
                raise HTTPException(status_code=403, detail="Invalid API credentials — check your key and secret.")
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
        except HTTPException:
            raise
        except httpx.HTTPStatusError as e:
            raise HTTPException(status_code=502, detail=f"Alpaca returned {e.response.status_code}")
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
    qty: float = Field(gt=0, allow_inf_nan=False)
    side: Literal["buy", "sell"]
    type: str = "market"
    time_in_force: str = "day"
    limit_price: Optional[float] = Field(default=None, gt=0, allow_inf_nan=False)


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
        "winRate": "Unverified",
        "avgReturn": "+12.4%",
        "tags": ["momentum", "intraday", "trend"],
        "params": {"fast_ema": 9, "slow_ema": 21, "trend_ema": 55, "stop_atr": 1.5, "tp_atr": 2.5},
        "file": "strategy_ema_vwap.py",
    },
    {
        "id": "orb",
        "name": "Opening Range Breakout",
        "description": "Trades breakouts above/below the first 30-minute range with ATR-based stops.",
        "risk": "High",
        "timeframe": "5m",
        "winRate": "Unverified",
        "avgReturn": "+18.7%",
        "tags": ["breakout", "morning", "volatility"],
        "params": {"orb_minutes": 30, "stop_atr": 1.0, "tp_atr": 2.0},
        "file": "strategy_orb.py",
    },
    {
        "id": "rsi",
        "name": "RSI Mean Reversion",
        "description": "Daily swing strategy: RSI(7) below 25 near the lower Bollinger Band; exits above RSI 55.",
        "risk": "Low",
        "timeframe": "1D",
        "winRate": "Unverified",
        "avgReturn": "+8.2%",
        "tags": ["mean-reversion", "oscillator", "swing"],
        "params": {"rsi_period": 7, "oversold": 25, "exit": 55},
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
        "supported": False,
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


def _bot_alive(strategy_id: str) -> bool:
    return runtime.alive(strategy_id)


def _log_tail(strategy_id, count=50):
    return list(runtime.logs.get(strategy_id, []))[-count:]


@app.get("/api/bot/status")
async def bot_status():
    # Build per-strategy status map
    statuses = {
        sid: {
            "running": _bot_alive(sid),
            "logs": _log_tail(sid),
        }
        for sid in bot_processes
    }
    any_running = any(v["running"] for v in statuses.values())
    active_ids = [sid for sid, v in statuses.items() if v["running"]]
    return {
        "running": any_running,
        "strategy": active_ids[0] if len(active_ids) == 1 else (active_ids or None),
        "strategies": statuses,
        "logs": _log_tail(active_ids[0] if active_ids else next(reversed(bot_processes), "")),
    }


@app.post("/api/bot/start")
async def bot_start(req: BotStartRequest):

    if not req.paper:
        raise HTTPException(status_code=403, detail="Live trading is disabled in this paper release.")
    # If this exact strategy is already running, no-op
    if _bot_alive(req.strategy):
        return {"status": "already_running", "strategy": req.strategy}

    if any(_bot_alive(sid) for sid in bot_processes):
        raise HTTPException(status_code=409, detail="Stop the active engine before selecting another strategy.")

    env = {
        **os.environ,
        "APCA_API_KEY_ID": req.api_key,
        "APCA_API_SECRET_KEY": req.secret_key,
        "TRADING_MODE": "paper" if req.paper else "live",
        "ALPACA_API_KEY": req.api_key,
        "ALPACA_SECRET_KEY": req.secret_key,
        "ALPACA_PAPER": "true" if req.paper else "false",
        "STRATEGY": req.strategy,
    }

    from backend.managed import store
    import hashlib
    settings = store.read()
    risk_id = hashlib.sha256(('paper:' + (settings.get('paper_account_id') or req.api_key)).encode()).hexdigest()[:24]
    env.update({
        'NEXLARA_RISK_STATE': str(Path(__file__).parent.parent / 'data' / ('risk-' + risk_id + '.json')),
        'NEXLARA_POSITION_SIZE_MULTIPLIER': str(settings['position_size_multiplier']),
        'NEXLARA_MAX_ORDER_VALUE': str(settings['max_order_value']),
        'NEXLARA_MAX_POSITION_PCT': str(settings['max_position_pct'] / 100),
        'NEXLARA_MAX_DAILY_LOSS_PCT': str(settings['max_daily_loss_pct'] / 100),
        'NEXLARA_MAX_POSITIONS': str(settings['max_positions']),
        'NEXLARA_ALLOCATION_MODE': settings['allocation_mode'],
        'NEXLARA_BUYING_POWER_RESERVE_PCT': str(settings['buying_power_reserve_pct']),
        'NEXLARA_MAX_GROSS_EXPOSURE_PCT': str(settings['max_gross_exposure_pct']),
        'NEXLARA_STARTING_CAPITAL': str(settings['starting_capital']),
        'NEXLARA_HALT_EQUITY': str(settings['halt_equity']),
        'CLOSE_ON_SHUTDOWN': 'true',
        'SHORTS_ENABLED': str(settings['shorts_enabled']).lower(),
        'NEWS_ENABLED': str(settings['news_enabled']).lower(),
        'STRATEGIES': json.dumps(settings['strategies']),
        'NEXLARA_MANAGED_AI': 'true',
        'NEXLARA_ACCOUNT_SCOPE': settings.get('paper_account_id','unconfigured'),
        'STRATEGY': '', 'NEXLARA_SIZING_BASIS': 'buying_power', 'KILL_SWITCH': 'false',
    })
    # The broker child only checks AI policy; the separate worker owns provider secrets.
    env.pop('ANTHROPIC_API_KEY',None)
    # Resolve bot script — check env override first, then common locations
    _candidates = [
        Path(os.environ.get("BOT_SCRIPT", "")),
        Path(__file__).parent.parent / "main.py",
        Path(__file__).parent / "main.py",
        Path("/opt/stock-agent/main.py"),
    ]
    bot_script = next((p for p in _candidates if p.name and p.is_file()), None)
    if bot_script is None:
        raise HTTPException(status_code=500, detail=f"Bot script not found. Set BOT_SCRIPT env var or place main.py alongside backend/.")

    try:
        proc = runtime.start(req.strategy, bot_script, env)
    except RuntimeError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception:
        raise HTTPException(status_code=500, detail="Bot process could not be launched. Check server logs.")
    await asyncio.sleep(0.25)
    if proc.poll() is not None:
        raise HTTPException(status_code=502, detail="Bot exited during startup. Check bot status logs.")
    return {"status": "starting", "strategy": req.strategy, "pid": proc.pid}


@app.post("/api/bot/stop")
async def bot_stop(strategy: Optional[str] = None):
    try:
        targets = await asyncio.to_thread(runtime.stop, strategy)
    except KeyError:
        raise HTTPException(status_code=404, detail="Unknown or inactive strategy")
    return {"status": "stopped", "stopped": targets}


@app.get("/api/bots")
async def list_bots():
    state = _read_bot_state()
    trades_today = state.get("trades_today", [])

    rows = []
    for i, (sid, meta) in enumerate(STRATEGY_META.items()):
        internal_name = {"ema_vwap": "EMA_VWAP", "orb": "ORB", "rsi": "RSI_BOUNCE"}[sid]
        strat_trades = [t for t in trades_today if t.get("strategy") in (sid, internal_name)]
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
    x_api_key: str = Header(...),
    x_secret_key: str = Header(...),
    x_paper: str = Header(default="true"),
):
    api_key = x_api_key
    secret_key = x_secret_key
    paper = x_paper.lower() == "true"

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


from backend.managed import router as workspace_router
app.include_router(workspace_router)
