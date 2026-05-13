# Live Stock Trading Bot

A fully automated multi-strategy trading bot for Alpaca, configured for a **$100 micro account** using fractional shares.

---

## RISK WARNING

**This bot trades with REAL MONEY. Losses are possible and likely.**

- You can lose some or all of your $100 investment.
- Past backtest performance does not guarantee future results.
- Automated trading carries risks including but not limited to: software bugs, API outages, network failures, unexpected market conditions, and slippage.
- This bot is provided as-is with no warranty. The author is not a financial advisor.
- **Never trade with money you cannot afford to lose.**
- **Monitor the bot actively, especially during the first few days of live trading.**

---

## Strategies

The bot uses three strategies, auto-selected per stock per day:

1. **EMA + VWAP Crossover Momentum** (Intraday, 5-min candles) — 9/21/55 EMA crossover with VWAP confirmation and volume filter. ATR-based stops with trailing stop.

2. **Opening Range Breakout** (Intraday, 5-min candles) — First 30 minutes define the range. Breakout trades after 10 AM with volume confirmation.

3. **RSI Bounce Mean Reversion** (Swing, daily candles) — RSI(7) < 25 with Bollinger Band touch and SMA50 trend filter. PDT-safe (holds overnight).

Short selling is **disabled** for this $100 configuration. The bot only takes long positions.

---

## Safety Features

- **Kill Switch**: Set `KILL_SWITCH=true` in `.env` to immediately close all positions and shut down.
- **Balance Sanity Check**: Refuses to start if account balance exceeds $200 (prevents running on wrong account).
- **Max Order Cap**: No single order can exceed $10.
- **Daily Loss Limit**: Stops trading if daily loss exceeds 2% of portfolio.
- **Drawdown Halt**: Halts completely if portfolio drops below $90.
- **PDT Protection**: Tracks day trades and never exceeds 3 in a rolling 5-day window. Automatically switches to swing-only mode when limit is reached.
- **Graceful Shutdown**: On Ctrl+C, cancels all orders and optionally closes all positions.
- **Error Recovery**: All API calls are wrapped with retry logic. Never crashes and leaves orphaned positions.

---

## Setup Instructions

### 1. Create an Alpaca Account

Sign up at [https://alpaca.markets](https://alpaca.markets). Fund your account with $100.

Generate **LIVE** API keys (not paper) from the dashboard.

### 2. Install Dependencies

```bash
cd stock-agent-live
pip install -r requirements.txt
```

### 3. Configure API Keys

Copy the example environment file and add your keys:

```bash
cp .env.example .env
```

Edit `.env` and replace the placeholder values:

```
APCA_API_KEY_ID=your_actual_key_here
APCA_API_SECRET_KEY=your_actual_secret_here
```

### 4. Run the Bot

```bash
python main.py
```

The bot will:
1. Validate your account
2. Download historical data
3. Start the scheduler
4. Trade automatically during market hours (9:30 AM - 4:00 PM ET)

### 5. Monitor

Watch the terminal output for trade entries, exits, and daily summaries. Logs are also saved to the `logs/` directory.

---

## File Structure

```
stock-agent-live/
  main.py                — Entry point, scheduling, lifecycle
  config.py              — All settings, thresholds, stock universe
  env_loader.py          — Loads .env, validates keys, checks kill switch
  account_manager.py     — Account checks, buying power, PDT tracking
  data_feed.py           — Alpaca REST for live/historical data
  indicators.py          — EMA, VWAP, RSI, Bollinger, ATR
  strategy_ema_vwap.py   — Strategy 1 (intraday momentum)
  strategy_orb.py        — Strategy 2 (opening range breakout)
  strategy_rsi.py        — Strategy 3 (swing mean reversion)
  strategy_selector.py   — Picks strategy, enforces PDT override
  order_manager.py       — Order submission, tracking, fills, cancellations
  risk_manager.py        — Position sizing, daily loss, drawdown, kill checks
  explainer.py           — Trade reasoning generator
  logger_setup.py        — File + console logging configuration
  utils.py               — Formatting, timezone, color output
  data/                  — Cached data and PDT tracking
  logs/                  — Daily trade logs
  .env                   — API keys + safety controls
  .env.example           — Template showing required variables
  requirements.txt       — Python dependencies
```

---

## Configuration

All parameters are in `config.py`. Key settings:

| Parameter | Value | Description |
|---|---|---|
| MAX_POSITION_PCT | 5% | Max position size per trade |
| MAX_CONCURRENT_POSITIONS | 3 | Max open positions at once |
| MAX_ORDER_VALUE | $10 | Hard cap per order |
| MAX_DAILY_LOSS_PCT | 2% | Daily loss limit |
| MAX_DRAWDOWN_PCT | 10% | Total drawdown halt |
| PDT_MAX_DAY_TRADES | 3 | Day trade limit (rolling 5 days) |

---

## Emergency Procedures

**To immediately stop the bot and close all positions:**

1. Set `KILL_SWITCH=true` in `.env`
2. Restart the bot: `python main.py`
3. It will close everything and exit.

**Or:**

1. Press Ctrl+C in the terminal
2. If `CLOSE_ON_SHUTDOWN=true`, positions will be closed automatically

**Manual override via Alpaca dashboard:**

You can always log into [https://app.alpaca.markets](https://app.alpaca.markets) to manually close positions or cancel orders.

---

## Important Notes

- The bot uses **fractional shares** for all orders since $5 positions can't buy whole shares of most stocks.
- All orders are **limit orders** (not market orders) to avoid slippage.
- The bot uses the **IEX data feed** (free tier). For better data, upgrade to SIP in your Alpaca account.
- SEC fees are tracked but negligible at this account size (~$0.000008 per $1 sold).
- The bot sleeps outside market hours to avoid consuming API quota.
- Swing trades (Strategy 3) are held overnight and survive bot restarts.
