# Stock Agent — Claude Code Reference

## Project Overview

A live algorithmic trading bot for Alpaca (paper/live), with a React dashboard, FastAPI backend proxy, Slack controller, and Claude AI wired in at two levels:
1. **Strategy Builder** — AI chat on the Strategy page helps users design new strategies (saved permanently)
2. **Claude Decision Layer** — every BUY signal and every discretionary EXIT signal passes through Claude Haiku before execution; hard stops always fire unconditionally

---

## Architecture

```
Market Data (Alpaca REST/IEX)
        │
    DataFeed (data_feed.py)
        │  historical bars + live polling + indicator computation
        ▼
Signal Engines (strategy_*.py)  ←─  strategy_selector.py chooses which to run
        │  returns "BUY" / "NONE" for entries; (should_exit, reason) for exits
        ▼
Claude Layer (claude_layer.py)   ←── Haiku-4-5, prompt-cached system prompt
        │  EXECUTE / SKIP + confidence + one-sentence reasoning
        ▼
Execution (order_manager.py + risk_manager.py)
        │  limit orders, fill polling, position tracking, daily halt
        ▼
  bot_state.json  ←── shared with FastAPI via Docker volume
```

---

## Containers (docker-compose.yml)

| Container       | Purpose                          | Port  |
|-----------------|----------------------------------|-------|
| `stockbot`      | Bot process + Slack controller   | —     |
| `stockbot-api`  | FastAPI backend proxy            | 8000  |
| `stockbot-web`  | React app served by nginx        | 80    |

All three share a `bot-data` volume (mounted at `/app/data`) and `bot-logs` volume (`/app/logs`).

### Deploy after editing Python files
```bash
# For bot files (main.py, claude_layer.py, strategy_*.py, etc.)
docker cp <file> stockbot:/app/<file>

# For backend
docker cp backend/main.py stockbot-api:/app/backend/main.py
docker restart stockbot-api

# For frontend — must rebuild
cd frontend && npm run build
docker cp dist/. stockbot-web:/usr/share/nginx/html/
# OR full rebuild:
docker compose build frontend && docker compose up -d frontend
```

---

## Key Files

### Bot (`/root/stock-agent-live/`)

| File | Role |
|---|---|
| `main.py` | Entry point. Scheduler, trading tick loop, `_scan_entries()`, `_check_exits()`, `_maybe_execute_entry()` |
| `claude_layer.py` | Claude Haiku decision layer. `ask_entry()` / `ask_exit()`. Falls back to EXECUTE on any error. |
| `config.py` | All constants: universe (30 stocks), risk limits, strategy thresholds, market hours |
| `data_feed.py` | `DataFeed` class — downloads bars, computes indicators, polls live bars, tracks opening ranges |
| `strategy_ema_vwap.py` | EMA(9/21/55) + VWAP intraday momentum (5-min). `check_signal(row)`, `check_exit(pos, row)`, `entry_details(row)` |
| `strategy_orb.py` | Opening Range Breakout — buys above first-30min high after 10 AM. `entry_details(row, orb)` |
| `strategy_rsi.py` | RSI(7) < 25 near lower Bollinger Band swing trade. `entry_details(daily_row)` |
| `strategy_selector.py` | Chooses which strategies apply to each symbol given daily indicators and gap% |
| `risk_manager.py` | Position sizing (5% of portfolio), daily loss halt, drawdown halt, `LivePosition` dataclass |
| `order_manager.py` | Limit orders, fill polling (30s timeout), `submit_buy()` / `submit_sell()` |
| `account_manager.py` | Alpaca account info, PDT count, buying power, startup validation |
| `explainer.py` | Prints trade explanations to terminal; `calc_confidence()` |
| `indicators.py` | Pure functions: `ema()`, `sma()`, `rsi()`, `vwap()`, `atr()`, `bollinger_bands()`, `volume_ma()` |
| `env_loader.py` | Reads `.env` into `os.environ`; returns config dict. Called at startup before anything else. |
| `logger_setup.py` | Structured logger with rotating file handler |
| `utils.py` | `now_et()`, `fmt_price()`, `fmt_pct()`, ANSI color helpers |
| `slack_controller.py` | Slack Bolt app — handles `!start/!stop/!status/!buy` and free-form AI chat using bot_state.json |
| `data/bot_state.json` | Written every tick by `_write_state()` — live positions, trades today, halted flag |
| `data/custom_strategies.json` | User-created strategies from AI Builder (persisted) |
| `data/strategy_likes.json` | `{strategy_id: count}` like counts |

### Backend (`/root/stock-agent-live/backend/main.py`)

FastAPI proxy. Key design notes:
- **Single bot** — `BOT_KEY = "main"`. No per-strategy bots.
- **Route order matters** — `/api/strategies/ai-consult` is registered BEFORE `/api/strategies/{strategy_id}` to prevent FastAPI treating "ai-consult" as an ID.
- Bot process is launched with `subprocess.Popen(["python", "main.py"])` from within the container.

#### API Routes

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/validate` | Validate Alpaca API keys |
| GET | `/api/account` | Alpaca account info |
| GET | `/api/positions` | Open positions |
| GET | `/api/orders` | Orders (status, limit params) |
| POST | `/api/orders` | Place order |
| DELETE | `/api/orders/{id}` | Cancel order |
| GET | `/api/portfolio/history` | Portfolio history chart data |
| GET | `/api/quotes` | Latest quotes for symbols |
| GET | `/api/strategies?sort=popular\|alpha` | All strategies (built-in + custom) with like counts |
| POST | `/api/strategies/ai-consult` | Claude Sonnet chat for strategy design |
| POST | `/api/strategies` | Create custom strategy |
| PUT | `/api/strategies/{id}` | Edit custom strategy (locked if bot running) |
| DELETE | `/api/strategies/{id}` | Delete custom strategy |
| POST | `/api/strategies/{id}/like` | Like a strategy |
| DELETE | `/api/strategies/{id}/like` | Unlike a strategy |
| GET | `/api/bot/status` | Bot running state + recent logs |
| POST | `/api/bot/start` | Start bot with credentials |
| POST | `/api/bot/stop` | Stop bot |
| POST | `/api/bot/test-order` | Place test order |
| GET | `/api/health` | Health check |

### Frontend (`/root/stock-agent-live/frontend/src/`)

| File | Role |
|---|---|
| `pages/Strategy.jsx` | Main strategy page — Browse tab, AI Builder tab, Start/Stop bot, like buttons, edit modal |
| `pages/Dashboard.jsx` | Portfolio overview, positions, chart |
| `pages/Stocks.jsx` | Stock quotes |
| `pages/News.jsx` | News feed |
| `pages/Onboarding.jsx` | First-run API key setup |
| `api/alpaca.js` | `api` object — all fetch calls, 15s default timeout (30s for `aiConsult`) |
| `contexts/AuthContext.jsx` | Stores API credentials in localStorage |

#### `api/alpaca.js` signatures
```js
api.strategies(sort)                    // GET /api/strategies?sort=...
api.createStrategy(body)                // POST /api/strategies
api.updateStrategy(id, body)            // PUT /api/strategies/{id}
api.deleteStrategy(id)                  // DELETE /api/strategies/{id}
api.likeStrategy(id)                    // POST /api/strategies/{id}/like
api.unlikeStrategy(id)                  // DELETE /api/strategies/{id}/like
api.aiConsult(messages)                 // POST /api/strategies/ai-consult (30s timeout)
api.botStatus()                         // GET /api/bot/status
api.botStart(body)                      // POST /api/bot/start
api.botStop()                           // POST /api/bot/stop
api.account(headers)                    // GET /api/account
api.positions(headers)                  // GET /api/positions
api.orders(headers, status, limit)      // GET /api/orders
api.placeOrder(headers, body)           // POST /api/orders
api.cancelOrder(headers, orderId)       // DELETE /api/orders/{id}
api.quotes(symbols, headers)            // GET /api/quotes?symbols=...
api.portfolioHistory(headers, period, timeframe)
```

---

## Trading Strategies

### EMA_VWAP (Intraday, 5-min)
- **Entry**: EMA(9) crosses above EMA(21), price > EMA(55) and > VWAP, volume > 1.2× MA
- **Exit (hard)**: stop_loss (1.5×ATR), take_profit (2.5×ATR), trailing_stop (activates at 1×ATR gain)
- **Exit (discretionary → Claude)**: signal_exit (EMA cross-down)
- **Indicators available**: ema9, ema21, ema55, vwap, atr, volume, vol_ma, close

### ORB (Intraday, 5-min)
- **Entry**: Close breaks above first-30min high after 10 AM, volume > 1.5× MA, daily EMA(20) uptrend
- **Exit (hard)**: stop_loss (below ORB low), take_profit
- **No discretionary exits** — both exits are hard
- **Indicators available**: orb_high, orb_low, orb_width, close, volume, vol_ma

### RSI_BOUNCE (Swing, daily)
- **Entry**: RSI(7) < 25, close near lower Bollinger Band, price > SMA(50)
- **Exit (hard)**: stop_loss (2%), time_stop (5 days)
- **Exit (discretionary → Claude)**: rsi_exit (RSI > 55), bb_mid_exit (price crosses BB midline)
- **Indicators available**: rsi7, bb_lower, bb_mid, bb_upper, sma50, close

---

## Claude Integration

### Decision Layer (`claude_layer.py`)
- Model: `claude-haiku-4-5` (low latency, cheap for per-tick decisions)
- System prompt cached with `cache_control: {"type": "ephemeral"}`
- Returns: `{"action": "EXECUTE"|"SKIP", "confidence": 0-100, "reasoning": "<15 words"}`
- **Always falls back to EXECUTE** on API error — never blocks trades
- Hard exits (`stop_loss`, `take_profit`, `time_stop`, `trailing_stop`) bypass Claude entirely

### AI Strategy Builder (`backend/main.py` → `/api/strategies/ai-consult`)
- Model: `claude-sonnet-4-6` with streaming disabled (30s timeout on frontend)
- Maintains conversation history in frontend state (`aiMessages`)
- Returns `{message, proposal}` — proposal is null until Claude produces a structured strategy
- Proposals saved to `data/custom_strategies.json` via "Build This Strategy" button

---

## Key Gotchas

1. **Lockfile per strategy ID**: `data/.bot_{strategy_id}.lock` — prevents duplicate bot instances. The `STRATEGY` env var defaults to `"default"` if unset.

2. **Pandas UserWarning suppressed**: `warnings.filterwarnings()` at the top of `main.py` (before the alpaca_trade_api import) silences `pd.Timestamp(unit='s')` warnings from the library.

3. **FastAPI route ordering**: `/api/strategies/ai-consult` MUST be registered before `/api/strategies/{strategy_id}`. FastAPI matches routes top-to-bottom; reversing this causes "ai-consult" to be treated as a strategy ID.

4. **Single bot architecture**: Only one `main.py` process runs all three strategies. `BOT_KEY = "main"` in backend. Before this was fixed, three processes ran simultaneously causing 90 API calls per poll cycle and duplicate trades.

5. **Shared Docker volumes**: `bot-data` is mounted in both `stockbot` and `stockbot-api` containers — that's how the API reads `bot_state.json` without HTTP calls.

6. **IEX feed**: All Alpaca REST bar requests use `feed="iex"` (free tier compatible). SIP feed requires paid subscription.

7. **ORB backfill**: `download_opening_range_bars()` is called before `compute_opening_ranges()` at 10 AM to backfill any bars that missed the live poll. Without this, ORB symbols with IEX delays would have < 6 bars and no range.

8. **Discretionary vs hard exit routing** in `_check_exits()`:
   ```python
   _HARD_EXITS = {"stop_loss", "take_profit", "time_stop", "trailing_stop"}
   # Hard exits → _execute_exit() directly
   # Others (signal_exit, rsi_exit, bb_mid_exit) → claude_layer.ask_exit() first
   ```

---

## Environment Variables (`.env`)

```
APCA_API_KEY_ID=...
APCA_API_SECRET_KEY=...
TRADING_MODE=paper          # or "live"
KILL_SWITCH=false
CLOSE_ON_SHUTDOWN=true
ANTHROPIC_API_KEY=...
SLACK_BOT_TOKEN=...
SLACK_APP_TOKEN=...
```

`env_loader.py` reads this file at startup and sets all keys into `os.environ`. Docker also injects them via `env_file: .env` in compose.

---

## Stock Universe

30 stocks across 3 tiers (scanned in priority order):
- **Tier 1** (10): AAPL, MSFT, GOOGL, AMZN, NVDA, META, TSLA, JPM, V, MA
- **Tier 2** (10): AMD, INTC, BAC, F, PLTR, SOFI, SNAP, NIO, COIN, UBER
- **Tier 3** (10): SPY, QQQ, NFLX, DIS, CRM, SHOP, PYPL, ORCL, BABA, RIVN

---

## Risk Limits

| Parameter | Value |
|---|---|
| Max position size | 5% of portfolio |
| Max concurrent positions | 3 |
| Max daily loss | 2% → stop trading for the day |
| Max drawdown | 10% → halt bot entirely |
| PDT limit | 3 day trades per rolling 5-day window |
