"""
Configuration — all parameters, thresholds, stock universe.
Designed for LIVE trading with $100 micro account.

Per-user overrides: this module is imported once per bot process, and the
backend spawns one bot per account with the user's saved settings injected as
CFG_* environment variables. The helpers below read those overrides at import
time, falling back to the defaults here for standalone runs.
"""
import os
from datetime import time as dtime


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, ""))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(float(os.getenv(name, "")))
    except (TypeError, ValueError):
        return default


def _env_list(name: str, default: list) -> list:
    raw = os.getenv(name, "")
    syms = [s.strip().upper() for s in raw.split(",") if s.strip()]
    return syms or default


# ─── Stock Universe ───────────────────────────────────────────────────────────
TIER_1 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
TIER_2 = ["AMD", "INTC", "BAC", "F", "PLTR", "SOFI", "SNAP", "NIO"]
STOCK_UNIVERSE = _env_list("CFG_STOCK_UNIVERSE", TIER_1 + TIER_2)

# ─── Account & Risk ──────────────────────────────────────────────────────────
STARTING_CAPITAL = 100.0
MAX_POSITION_PCT = _env_float("CFG_MAX_POSITION_PCT", 0.05)        # 5% of portfolio per trade
MAX_CONCURRENT_POSITIONS = _env_int("CFG_MAX_CONCURRENT_POSITIONS", 3)
MAX_DAILY_LOSS_PCT = _env_float("CFG_MAX_DAILY_LOSS_PCT", 0.02)    # 2% daily loss → stop trading
MAX_DRAWDOWN_PCT = 0.10            # 10% drawdown → HALT bot
HALT_THRESHOLD_VALUE = 90.0        # $90 absolute halt level
MAX_ORDER_VALUE = _env_float("CFG_MAX_ORDER_VALUE", 10.0)          # hard cap: no single order
SANITY_MAX_BALANCE = 200.0         # refuse to start if account > $200

# ─── PDT (Pattern Day Trader) ────────────────────────────────────────────────
PDT_MAX_DAY_TRADES = 3             # max day trades in rolling 5-day window
PDT_WINDOW_DAYS = 5

# ─── Order Execution ─────────────────────────────────────────────────────────
LIMIT_OFFSET_PCT = 0.0005          # 0.05% offset for limit orders
ORDER_POLL_INTERVAL = 2            # seconds between fill checks
ORDER_POLL_TIMEOUT = 30            # max seconds to wait for fill
SEC_FEE_RATE = 8.0 / 1_000_000    # $8 per $1M sold

# ─── Strategy 1: EMA + VWAP Crossover Momentum (Intraday, 5-min) ─────────────
S1_EMA_FAST = 9
S1_EMA_SLOW = 21
S1_EMA_TREND = 55
S1_ATR_PERIOD = 14
S1_STOP_ATR = 1.5
S1_TP_ATR = 2.5                    # R:R = 1.67
S1_TRAIL_ACTIVATE_ATR = 1.0
S1_TRAIL_STOP_ATR = 1.0
S1_VOLUME_MA = 20
S1_VOLUME_THRESHOLD = 1.2

# ─── Strategy 2: Opening Range Breakout (Intraday, 5-min) ────────────────────
S2_ORB_MINUTES = 30                # first 30 minutes define the range
S2_EMA_PERIOD = 20                 # daily EMA for trend filter
S2_VOLUME_THRESHOLD = 1.5
S2_ATR_PERIOD = 14

# ─── Strategy 3: Mean Reversion RSI Bounce (Swing, daily) ────────────────────
S3_RSI_PERIOD = 7
S3_RSI_OVERSOLD = 25
S3_RSI_EXIT = 55                   # exit when RSI > 55
S3_BB_PERIOD = 20
S3_BB_STD = 2
S3_SMA_PERIOD = 50
S3_STOP_LOSS_PCT = 0.02            # 2% stop
S3_MAX_HOLD_DAYS = 5

# ─── Strategy 4: VWAP Breakdown Short (Intraday, 5-min) ──────────────────────
# Bearish counterpart to S1: short when 9 EMA crosses below 21 EMA, price is
# below the 55 EMA and below VWAP, on rising volume. PAPER ONLY by default.
S4_STOP_ATR = 1.5                  # stop ABOVE entry for shorts
S4_TP_ATR = 2.5                    # target BELOW entry
S4_VOLUME_THRESHOLD = 1.2

# ─── Strategy 5: News-Driven Sentiment (event, intraday) ─────────────────────
# Pulls recent Alpaca news headlines for each symbol and scores sentiment with
# the user's Anthropic key. Strong positive → long, strong negative → short.
# PAPER ONLY by default. Needs ANTHROPIC_API_KEY injected by the backend.
NEWS_LOOKBACK_HOURS = 24           # only consider headlines this fresh
NEWS_MAX_ARTICLES = 8              # headlines per symbol sent to the model
NEWS_SENTIMENT_THRESHOLD = 0.5     # |score| must exceed this to act (-1..1)
NEWS_STOP_PCT = 0.02               # 2% stop from entry
NEWS_TP_PCT = 0.04                 # 4% target from entry
NEWS_MODEL = "claude-sonnet-4-6"

# ─── Smarter sell-side exits (applies to all LONG positions) ─────────────────
# Profit-lock: once a long is up >= activate%, exit if it gives back more than
# giveback fraction of its peak gain. Complements per-strategy stops/targets.
PROFIT_LOCK_ACTIVATE_PCT = 0.03    # arm after +3% unrealized
PROFIT_LOCK_GIVEBACK = 0.40        # exit if 40% of peak gain is surrendered

# ─── Daily Universal Scanner ─────────────────────────────────────────────────
# At market open the bot scans a broad pool of liquid stocks and trades the
# best-ranked names for the day instead of a fixed list. Per-user overridable.
SCANNER_ENABLED = os.getenv("CFG_SCANNER_ENABLED", "true").lower() == "true"
SCANNER_MAX_SYMBOLS = _env_int("CFG_SCANNER_MAX_SYMBOLS", 50)   # day's active universe size
SCANNER_POOL_SIZE = _env_int("CFG_SCANNER_POOL_SIZE", 100)      # candidates to evaluate (Alpaca most-actives caps top=100)
SCANNER_MIN_PRICE = _env_float("CFG_SCANNER_MIN_PRICE", 3.0)    # skip sub-$3 names
SCANNER_MIN_DOLLAR_VOL = _env_float("CFG_SCANNER_MIN_DOLLAR_VOL", 5_000_000.0)

# ─── Strategy Selection Thresholds ───────────────────────────────────────────
SEL_ATR_PCT_HIGH = 0.02            # ATR% > 2% → S1
SEL_GAP_PCT = 0.01                 # Gap > 1% → S2
SEL_ATR_PCT_LOW = 0.015            # ATR% < 1.5% → S3
SEL_RANGE_PCT = 0.08               # 20-day range < 8% → S3

# ─── Market Hours (Eastern Time) ─────────────────────────────────────────────
MARKET_OPEN = dtime(9, 30)
MARKET_CLOSE = dtime(16, 0)
PRE_MARKET_WAKE = dtime(9, 15)     # wake up and prep
TIME_STOP = dtime(15, 30)          # close intraday 30 min before close
ORB_END = dtime(10, 0)             # opening range period ends

# ─── Data ─────────────────────────────────────────────────────────────────────
LOOKBACK_DAYS_5M = 5               # 5 days of 5-min bars for indicators
LOOKBACK_DAYS_DAILY = 60           # 60 days of daily bars for SMA50, BB, RSI
DATA_DIR = "data"
LOGS_DIR = "logs"

# ─── Reconnection ────────────────────────────────────────────────────────────
WS_RECONNECT_BASE = 1              # base seconds for exponential backoff
WS_RECONNECT_MAX = 60              # max seconds between reconnect attempts
API_RETRY_DELAY = 5                # seconds to wait before API retry
