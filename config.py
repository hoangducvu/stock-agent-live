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
