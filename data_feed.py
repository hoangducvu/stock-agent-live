"""
Data Feed — Alpaca REST for historical bars, live bar aggregation,
and pre-market gap calculation.
"""
import time
import threading
import concurrent.futures
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional
from logger_setup import get_logger
import config
from utils import now_et
import indicators as ind

_API_TIMEOUT = 10  # seconds per Alpaca REST call


class DataFeed:
    """
    Manages historical data download and live 5-min candle tracking.
    Uses Alpaca REST API for bars (compatible with free tier).
    """

    def __init__(self, api):
        self.api = api
        self.log = get_logger()

        # Historical candle DataFrames: {symbol: DataFrame}
        self.bars_5m: Dict[str, pd.DataFrame] = {}
        self.bars_daily: Dict[str, pd.DataFrame] = {}

        # Pre-computed indicators (refreshed on each new candle)
        self.indicators_5m: Dict[str, pd.DataFrame] = {}
        self.indicators_daily: Dict[str, pd.DataFrame] = {}

        # Opening ranges for ORB strategy: {symbol: {"high": float, "low": float}}
        self.opening_ranges: Dict[str, dict] = {}

        # Gaps: {symbol: gap_pct}
        self.gaps: Dict[str, float] = {}

        # Last known prices
        self.last_prices: Dict[str, float] = {}

    # ─── Historical Data Download ────────────────────────────────────────

    def download_historical(self, symbols: list):
        """Download historical 5-min and daily bars for all symbols."""
        self.log.info(f"Downloading historical data for {len(symbols)} symbols...")

        for sym in symbols:
            try:
                self._download_5m(sym)
                self._download_daily(sym)
                bars5 = len(self.bars_5m.get(sym, []))
                barsd = len(self.bars_daily.get(sym, []))
                self.log.debug(f"  {sym}: {bars5} 5m bars, {barsd} daily bars")
            except Exception as e:
                self.log.error(f"  {sym}: download error — {e}")

        self.log.info(
            f"Data ready: {len(self.bars_5m)}/{len(symbols)} stocks with 5m, "
            f"{len(self.bars_daily)}/{len(symbols)} with daily"
        )

    def _download_5m(self, symbol: str):
        """Download 5-minute bars using Alpaca REST."""
        try:
            end = now_et()
            start = end - timedelta(days=config.LOOKBACK_DAYS_5M + 3)

            bars = self.api.get_bars(
                symbol,
                "5Min",
                start=start.strftime("%Y-%m-%dT%H:%M:%S-04:00"),
                end=end.strftime("%Y-%m-%dT%H:%M:%S-04:00"),
                feed="iex",
                limit=10000,
            )

            if not bars:
                return

            data = []
            for b in bars:
                data.append({
                    "Datetime": pd.Timestamp(b.t),
                    "Open": float(b.o),
                    "High": float(b.h),
                    "Low": float(b.l),
                    "Close": float(b.c),
                    "Volume": int(b.v),
                })

            df = pd.DataFrame(data)
            df.set_index("Datetime", inplace=True)
            df.index = df.index.tz_convert("US/Eastern")
            self.bars_5m[symbol] = df

            if len(df) > 0:
                self.last_prices[symbol] = df["Close"].iloc[-1]

        except Exception as e:
            self.log.error(f"5m download failed for {symbol}: {e}")

    def _download_daily(self, symbol: str):
        """Download daily bars using Alpaca REST."""
        try:
            end = now_et()
            start = end - timedelta(days=config.LOOKBACK_DAYS_DAILY + 10)

            bars = self.api.get_bars(
                symbol,
                "1Day",
                start=start.strftime("%Y-%m-%d"),
                end=end.strftime("%Y-%m-%d"),
                feed="iex",
                limit=10000,
            )

            if not bars:
                return

            data = []
            for b in bars:
                data.append({
                    "Date": pd.Timestamp(b.t).date(),
                    "Open": float(b.o),
                    "High": float(b.h),
                    "Low": float(b.l),
                    "Close": float(b.c),
                    "Volume": int(b.v),
                })

            df = pd.DataFrame(data)
            df.set_index("Date", inplace=True)
            df.index = pd.DatetimeIndex(df.index)
            self.bars_daily[symbol] = df

        except Exception as e:
            self.log.error(f"Daily download failed for {symbol}: {e}")

    # ─── Indicator Computation ───────────────────────────────────────────

    def compute_indicators(self, symbols: list):
        """Compute all indicators on current data for all symbols."""
        for sym in symbols:
            self._compute_5m_indicators(sym)
            self._compute_daily_indicators(sym)

    def _compute_5m_indicators(self, symbol: str):
        """Compute 5-min indicators for a symbol."""
        df = self.bars_5m.get(symbol)
        if df is None or len(df) < config.S1_EMA_TREND:
            return

        out = df.copy()
        out["ema9"] = ind.ema(df["Close"], config.S1_EMA_FAST)
        out["ema21"] = ind.ema(df["Close"], config.S1_EMA_SLOW)
        out["ema55"] = ind.ema(df["Close"], config.S1_EMA_TREND)
        out["vwap"] = ind.vwap(df)
        out["atr"] = ind.atr(df, config.S1_ATR_PERIOD)
        out["vol_ma"] = ind.volume_ma(df["Volume"], config.S1_VOLUME_MA)

        # EMA crossover detection
        out["ema_fast_above"] = out["ema9"] > out["ema21"]
        prev = out["ema_fast_above"].shift(1)
        out["ema_cross_up"] = out["ema_fast_above"] & ~prev.astype(bool)
        out["ema_cross_down"] = ~out["ema_fast_above"] & prev.astype(bool)

        self.indicators_5m[symbol] = out

    def _compute_daily_indicators(self, symbol: str):
        """Compute daily indicators for a symbol."""
        df = self.bars_daily.get(symbol)
        if df is None or len(df) < config.S3_SMA_PERIOD:
            return

        out = df.copy()
        out["rsi7"] = ind.rsi(df["Close"], config.S3_RSI_PERIOD)
        out["bb_mid"], out["bb_upper"], out["bb_lower"] = ind.bollinger_bands(
            df["Close"], config.S3_BB_PERIOD, config.S3_BB_STD
        )
        out["sma50"] = ind.sma(df["Close"], config.S3_SMA_PERIOD)
        out["ema20"] = ind.ema(df["Close"], config.S2_EMA_PERIOD)
        out["atr14"] = ind.atr(df, 14)

        self.indicators_daily[symbol] = out

    # ─── Live Bar Append ─────────────────────────────────────────────────

    def append_bar(self, symbol: str, bar_data: dict):
        """
        Append a completed 5-min bar and recompute indicators.
        bar_data: {"Open", "High", "Low", "Close", "Volume", "Datetime"}
        """
        if symbol not in self.bars_5m:
            return

        idx = pd.Timestamp(bar_data["Datetime"])
        if idx.tzinfo is not None:
            idx = idx.tz_convert("US/Eastern")
        else:
            idx = idx.tz_localize("US/Eastern")

        new_row = pd.DataFrame([{
            "Open": bar_data["Open"],
            "High": bar_data["High"],
            "Low": bar_data["Low"],
            "Close": bar_data["Close"],
            "Volume": bar_data["Volume"],
        }], index=[idx])

        self.bars_5m[symbol] = pd.concat([self.bars_5m[symbol], new_row])

        # Keep only last N bars to avoid memory bloat
        max_bars = 78 * config.LOOKBACK_DAYS_5M  # 78 bars per day
        if len(self.bars_5m[symbol]) > max_bars:
            self.bars_5m[symbol] = self.bars_5m[symbol].iloc[-max_bars:]

        self.last_prices[symbol] = bar_data["Close"]
        self._compute_5m_indicators(symbol)

    # ─── Pre-Market Gap Calculation ──────────────────────────────────────

    def calculate_gaps(self, symbols: list):
        """
        Calculate overnight gaps for each symbol.
        Gap = (today's first bar open - yesterday's close) / yesterday's close
        """
        self.gaps.clear()

        for sym in symbols:
            daily = self.bars_daily.get(sym)
            if daily is None or len(daily) < 2:
                continue

            prev_close = daily["Close"].iloc[-1]

            # Try to get today's opening price from 5m data
            bars5 = self.bars_5m.get(sym)
            if bars5 is not None and len(bars5) > 0:
                today = now_et().date()
                if hasattr(bars5.index, "date"):
                    today_bars = bars5[bars5.index.date == today]
                else:
                    today_bars = bars5.tail(1)

                if len(today_bars) > 0:
                    today_open = today_bars.iloc[0]["Open"]
                    gap = (today_open - prev_close) / prev_close
                    self.gaps[sym] = gap

        self.log.info(
            f"Gaps calculated for {len(self.gaps)} symbols. "
            f"Notable: {self._notable_gaps()}"
        )

    def _notable_gaps(self) -> str:
        """Return string of stocks with gaps > 1%."""
        notable = [(s, g) for s, g in self.gaps.items() if abs(g) > 0.01]
        if not notable:
            return "none > 1%"
        return ", ".join(f"{s} {g*100:+.1f}%" for s, g in notable)

    # ─── Opening Range ───────────────────────────────────────────────────

    def download_opening_range_bars(self, symbols: list):
        """
        Download today's 9:25–10:05 ET bars for any symbol that doesn't yet
        have 6 today-bars in memory.  Called by compute_orb() before
        compute_opening_ranges() so the range calc always has full data.
        poll_latest_bars(limit=1) only appends the newest bar per tick, so
        symbols that were late to IEX or missed a tick would be short bars.
        """
        today = now_et().date()
        start_str = f"{today}T09:25:00-04:00"
        end_str   = f"{today}T10:05:00-04:00"

        for sym in symbols:
            bars5 = self.bars_5m.get(sym)
            today_count = 0
            if bars5 is not None and hasattr(bars5.index, "date"):
                today_count = (bars5.index.date == today).sum()

            if today_count >= 6:
                continue  # already have enough bars

            try:
                bars = self._fetch_bars(
                    sym, "5Min",
                    start=start_str, end=end_str,
                    feed="iex", limit=20,
                )
                if not bars:
                    continue

                for b in bars:
                    ts = pd.Timestamp(b.t)
                    if ts.tzinfo is not None:
                        ts = ts.tz_convert("US/Eastern")
                    else:
                        ts = ts.tz_localize("US/Eastern")

                    existing = self.bars_5m.get(sym)
                    if existing is not None and ts in existing.index:
                        continue

                    bar_data = {
                        "Open": float(b.o), "High": float(b.h),
                        "Low": float(b.l),  "Close": float(b.c),
                        "Volume": int(b.v), "Datetime": ts,
                    }
                    self.append_bar(sym, bar_data)
                    self.last_prices[sym] = float(b.c)

            except Exception as e:
                self.log.debug(f"ORB bar download failed for {sym}: {e}")

    def compute_opening_ranges(self, symbols: list):
        """
        Compute the opening range (first 30 min high/low) for today.
        Should be called after 10:00 AM ET.
        """
        self.opening_ranges.clear()
        today = now_et().date()

        for sym in symbols:
            bars5 = self.bars_5m.get(sym)
            if bars5 is None or len(bars5) == 0:
                continue

            if hasattr(bars5.index, "date"):
                today_bars = bars5[bars5.index.date == today]
            else:
                continue

            if len(today_bars) < 6:  # need at least 6 bars (30 min)
                continue

            # First 6 bars = 30 minutes (9:30-10:00)
            orb_bars = today_bars.iloc[:6]
            self.opening_ranges[sym] = {
                "high": orb_bars["High"].max(),
                "low": orb_bars["Low"].min(),
            }

        self.log.info(f"Opening ranges computed for {len(self.opening_ranges)} symbols")

    # ─── Price Polling (REST fallback) ───────────────────────────────────

    def _fetch_bars(self, sym: str, timeframe: str, **kwargs):
        """Wrapper around api.get_bars with a hard timeout."""
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            future = ex.submit(self.api.get_bars, sym, timeframe, **kwargs)
            try:
                return future.result(timeout=_API_TIMEOUT)
            except concurrent.futures.TimeoutError:
                self.log.debug(f"API timeout for {sym} ({timeframe})")
                return []

    def poll_latest_bars(self, symbols: list):
        """
        Poll latest 5-min bars via REST. Use as fallback when
        websocket is unavailable. Returns list of new bars.
        """
        new_bars = []

        for sym in symbols:
            try:
                bars = self._fetch_bars(sym, "5Min", limit=1, feed="iex")
                if bars:
                    b = bars[-1]
                    ts = pd.Timestamp(b.t)
                    if ts.tzinfo is not None:
                        ts = ts.tz_convert("US/Eastern")
                    else:
                        ts = ts.tz_localize("US/Eastern")

                    # Check if this bar is new
                    existing = self.bars_5m.get(sym)
                    if existing is not None and len(existing) > 0:
                        last_ts = existing.index[-1]
                        if ts <= last_ts:
                            continue  # not a new bar

                    bar_data = {
                        "Open": float(b.o),
                        "High": float(b.h),
                        "Low": float(b.l),
                        "Close": float(b.c),
                        "Volume": int(b.v),
                        "Datetime": ts,
                    }
                    self.append_bar(sym, bar_data)
                    new_bars.append((sym, bar_data))

            except Exception as e:
                self.log.debug(f"Bar poll error for {sym}: {e}")

        return new_bars

    # ─── Accessors ───────────────────────────────────────────────────────

    def get_latest_5m(self, symbol: str) -> Optional[pd.Series]:
        """Get the most recent 5-min indicator row for a symbol."""
        df = self.indicators_5m.get(symbol)
        if df is not None and len(df) > 0:
            return df.iloc[-1]
        return None

    def get_latest_daily(self, symbol: str) -> Optional[pd.Series]:
        """Get the most recent daily indicator row for a symbol."""
        df = self.indicators_daily.get(symbol)
        if df is not None and len(df) > 0:
            return df.iloc[-1]
        return None

    def get_last_price(self, symbol: str) -> float:
        """Get last known price for a symbol."""
        return self.last_prices.get(symbol, 0.0)
