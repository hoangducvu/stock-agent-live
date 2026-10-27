"""
Configuration — all parameters, thresholds, stock universe.
Designed for LIVE trading with $100 micro account.
"""
from datetime import time as dtime

# ─── Stock Universe ───────────────────────────────────────────────────────────
TIER_1 = ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA"]
TIER_2 = ["AMD", "INTC", "BAC", "F", "PLTR", "SOFI", "SNAP", "NIO"]
STOCK_UNIVERSE = TIER_1 + TIER_2

# ─── Account & Risk ──────────────────────────────────────────────────────────
STARTING_CAPITAL = 100.0
MAX_POSITION_PCT = 0.05            # 5% of portfolio per trade ($5 initially)
MAX_CONCURRENT_POSITIONS = 3       # tight concentration for $100
MAX_DAILY_LOSS_PCT = 0.02          # 2% daily loss → stop trading
MAX_DRAWDOWN_PCT = 0.10            # 10% drawdown → HALT bot
HALT_THRESHOLD_VALUE = 90.0        # $90 absolute halt level
MAX_ORDER_VALUE = 10.0             # hard cap: no single order > $10
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

# ─── Short Strategies ────────────────────────────────────────────────────────
EXTENSION_MAX_PCT_ABOVE_EMA21 = 0.03   # reject short if already >3% extended below EMA21
SHORT_RSI_OVERBOUGHT = 75              # RSI(7) threshold for RSI_FADE entry
SHORT_RSI_EXIT = 45                    # cover when RSI falls back to neutral
SHORT_STOP_PCT_MIN = 0.02             # 2% stop above entry for RSI_FADE short

# ─── Universe Scanner ────────────────────────────────────────────────────────
SMALL_CAP_WATCHLIST: list = []         # extend with custom symbols as desired
UNIVERSE_DAILY_MAX = 60               # max intraday symbols after mover injection
UNIVERSE_SWING_MAX = 40               # max swing symbols
UNIVERSE_MIN_PRICE = 1.0              # drop penny stocks
UNIVERSE_MAX_PRICE = 10_000.0         # no hard upper cap

# ─── Pre-market News Scanner ─────────────────────────────────────────────────
PREMARKET_NEWS_LOOKBACK_HOURS = 14    # hours of news history to fetch
PREMARKET_MIN_CONFIDENCE = 75         # minimum Claude confidence score to act
PREMARKET_MAX_ENTRIES = 3             # max news-driven orders per pre-market run
PREMARKET_LIMIT_OFFSET_PCT = 0.001    # 0.1% above ref price for pre-market limit buy


# Validated dashboard overrides, passed only to the supervised engine.
import os as _os
import math as _math
def _setting(name, default, minimum, maximum):
    value = float(_os.environ.get('NEXLARA_' + name, default))
    if not _math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError('Invalid dashboard setting: ' + name)
    return value
MAX_ORDER_VALUE = _setting('MAX_ORDER_VALUE', MAX_ORDER_VALUE, 1, 10000)
MAX_POSITION_PCT = _setting('MAX_POSITION_PCT', MAX_POSITION_PCT, .001, .10)
MAX_DAILY_LOSS_PCT = _setting('MAX_DAILY_LOSS_PCT', MAX_DAILY_LOSS_PCT, .001, .05)
MAX_CONCURRENT_POSITIONS = int(_setting('MAX_POSITIONS', MAX_CONCURRENT_POSITIONS, 1, 50))
STARTING_CAPITAL = _setting('STARTING_CAPITAL', STARTING_CAPITAL, 10, 1000000)
HALT_THRESHOLD_VALUE = _setting('HALT_EQUITY', HALT_THRESHOLD_VALUE, 0, 1000000)
if HALT_THRESHOLD_VALUE >= STARTING_CAPITAL:
    raise ValueError('Equity halt must be below reference capital')

# Adaptive intraday exits. Checked by the existing five-minute engine cycle.
SCALP_MAX_HOLD_MINUTES = _setting('SCALP_MAX_HOLD_MINUTES', 30, 1, 240)
SCALP_STOP_ATR = _setting('SCALP_STOP_ATR', 1.5, .1, 10)
SCALP_TRAIL_ACTIVATE_ATR = _setting('SCALP_TRAIL_ACTIVATE_ATR', 1.0, .1, 10)
SCALP_TRAIL_ATR = _setting('SCALP_TRAIL_ATR', .75, .1, 10)

POSITION_SIZE_MULTIPLIER = _setting('POSITION_SIZE_MULTIPLIER', 1, 1, 20)

ALLOCATION_MODE = _os.getenv('NEXLARA_ALLOCATION_MODE','percentage')
if ALLOCATION_MODE not in {'percentage','fill_slots'}:raise ValueError('Invalid allocation mode')
BUYING_POWER_RESERVE_PCT = _setting('BUYING_POWER_RESERVE_PCT',5,1,50)
MAX_GROSS_EXPOSURE = _setting('MAX_GROSS_EXPOSURE_PCT',400,10,400)/100
