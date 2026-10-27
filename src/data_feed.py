"""
Data Feed — Alpaca REST for historical bars, live bar aggregation,
and pre-market gap calculation.
"""
import time
import threading
import queue
import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Optional
from logger_setup import get_logger
import config
from utils import now_et, ET
import indicators as ind

_API_TIMEOUT = 10  # seconds per Alpaca REST call


def _bar_timestamp(bar):
    """Parse Alpaca's wire timestamp without the legacy SDK string/unit warning."""
    raw = getattr(bar, '_raw', None)
    value = raw['t'] if isinstance(raw, dict) and 't' in raw else bar.t
    if isinstance(value, (int, float)):
        stamp = pd.Timestamp(value, unit='s', tz='UTC')
    else:
        stamp = pd.Timestamp(value)
        if stamp.tzinfo is None:
            stamp = stamp.tz_localize('UTC')
    return stamp.tz_convert(ET)


class DataFeed:
    """
    Manages historical data download and live 5-min candle tracking.
    Uses Alpaca REST API for bars (compatible with free tier).
    """

    def __init__(self, api):
        self.api = api
        self._fetch_lock = threading.Lock()
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
        self.gap_details: Dict[str, dict] = {}

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
                start=start.isoformat(),
                end=(pd.Timestamp(end).floor('5min') - pd.Timedelta(microseconds=1)).isoformat(),
                feed="iex",
                sort="asc",
                limit=10000,
            )

            if not bars:
                return

            data = []
            for b in bars:
                data.append({
                    "Datetime": _bar_timestamp(b),
                    "Open": float(b.o),
                    "High": float(b.h),
                    "Low": float(b.l),
                    "Close": float(b.c),
                    "Volume": int(b.v),
                })

            df = pd.DataFrame(data)
            df = df.set_index("Datetime")
            df.index = df.index.tz_convert(ET)
            df = df[~df.index.duplicated(keep='last')].sort_index()
            df = df[df.index + pd.Timedelta(minutes=5) <= end]
            self.bars_5m[symbol] = df

            if len(df) > 0:
                self.last_prices[symbol] = df["Close"].iloc[-1]

        except Exception as e:
            self.log.error(f"5m download failed for {symbol}: {e}")

    def _download_daily(self, symbol: str):
        """Download daily bars using Alpaca REST."""
        try:
            end = now_et()
            lookback = max(config.LOOKBACK_DAYS_DAILY + 10, 310) if 'trend_swing' in __import__('os').getenv('STRATEGIES','') else config.LOOKBACK_DAYS_DAILY + 10
            start = end - timedelta(days=lookback)

            bars = self.api.get_bars(
                symbol,
                "1Day",
                start=start.strftime("%Y-%m-%d"),
                end=end.replace(hour=0, minute=0, second=0, microsecond=0).isoformat(),
                feed="iex",
                sort="asc",
                limit=10000,
            )

            if not bars:
                return

            data = []
            for b in bars:
                data.append({
                    "Date": _bar_timestamp(b).date(),
                    "Open": float(b.o),
                    "High": float(b.h),
                    "Low": float(b.l),
                    "Close": float(b.c),
                    "Volume": int(b.v),
                })

            df = pd.DataFrame(data)
            df = df.set_index("Date")
            df.index = pd.DatetimeIndex(df.index)
            df = df[~df.index.duplicated(keep='last')].sort_index()
            df = df[df.index.date < end.date()]
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
        out['previous_close'] = df['Close'].shift(1)
        out['prior_high20'] = df['High'].rolling(20).max().shift(1)
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
        out['sma200'] = ind.sma(df['Close'],200)
        out['rsi14'] = ind.rsi(df['Close'],14)
        out['momentum20'] = df['Close'].pct_change(20)
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
        idx = pd.Timestamp(bar_data["Datetime"])
        if idx.tzinfo is not None:
            idx = idx.tz_convert(ET)
        else:
            idx = idx.tz_localize(ET)

        new_row = pd.DataFrame([{
            "Open": bar_data["Open"],
            "High": bar_data["High"],
            "Low": bar_data["Low"],
            "Close": bar_data["Close"],
            "Volume": bar_data["Volume"],
        }], index=[idx])

        existing = self.bars_5m.get(symbol)
        if existing is not None and isinstance(existing.index, pd.DatetimeIndex):
            existing = existing.copy()
            existing.index = existing.index.tz_convert(ET) if existing.index.tz is not None else existing.index.tz_localize(ET)
        merged = pd.concat([existing, new_row]) if existing is not None else new_row
        self.bars_5m[symbol] = merged[~merged.index.duplicated(keep='last')].sort_index()

        # Keep only last N bars to avoid memory bloat
        max_bars = 78 * config.LOOKBACK_DAYS_5M  # 78 bars per day
        if len(self.bars_5m[symbol]) > max_bars:
            self.bars_5m[symbol] = self.bars_5m[symbol].iloc[-max_bars:]

        self.last_prices[symbol] = float(self.bars_5m[symbol]['Close'].iloc[-1])
        self._compute_5m_indicators(symbol)

    # ─── Pre-Market Gap Calculation ──────────────────────────────────────

    def calculate_gaps(self, symbols: list, log_summary=True):
        """
        Calculate overnight gaps for each symbol.
        Gap = (09:30 ET bar open - prior completed daily close) / prior close.
        Missing opening bars remain unavailable, rather than using a later bar.
        """
        self.gaps.clear()
        old_details = self.gap_details
        self.gap_details = {}
        now = now_et()
        today = now.date()
        opening = pd.Timestamp(datetime.combine(today, datetime.min.time(), tzinfo=ET)).replace(hour=9, minute=30)

        for sym in symbols:
            daily = self.bars_daily.get(sym)
            if daily is None or daily.empty or not isinstance(daily.index, pd.DatetimeIndex):
                continue
            completed = daily[daily.index.date < today].sort_index()
            if completed.empty:
                continue
            prev_close = float(completed['Close'].iloc[-1])
            bars5 = self.bars_5m.get(sym)
            if (bars5 is None or bars5.empty or not isinstance(bars5.index, pd.DatetimeIndex)
                    or bars5.index.tz is None or opening not in bars5.index
                    or opening + pd.Timedelta(minutes=5) > now):
                continue
            today_open = float(bars5.loc[[opening], 'Open'].iloc[-1])
            if not (np.isfinite(prev_close) and prev_close > 0 and np.isfinite(today_open) and today_open > 0):
                continue
            gap = (today_open - prev_close) / prev_close
            self.gaps[sym] = gap
            details = dict(session=today.isoformat(), feed='iex',
                           previous_close_date=completed.index[-1].date().isoformat(),
                           previous_close=prev_close, opening_timestamp=opening.isoformat(),
                           opening_price=today_open, gap_pct=gap)
            self.gap_details[sym] = details
            if details != old_details.get(sym):
                self.log.info(
                    f"{sym} opening gap {gap:+.2%}: 09:30 ET open ${today_open:.4f} "
                    f"vs {details['previous_close_date']} close ${prev_close:.4f}; "
                    f"session={today}, feed=iex (not live daily change)"
                )

        if log_summary:
            self.log.info(
                f"Opening gaps available for {len(self.gaps)}/{len(symbols)} symbols "
                f"on {today} (09:30 ET vs prior close, feed=iex). "
                f"Notable: {self._notable_gaps()}"
            )

    def _opening_range_bars(self, symbol, now):
        """Return only today's completed bars in the 09:30–10:00 ET window."""
        bars = self.bars_5m.get(symbol)
        if bars is None or bars.empty or not isinstance(bars.index, pd.DatetimeIndex) or bars.index.tz is None:
            return pd.DataFrame()
        bars = bars.copy()
        bars.index = bars.index.tz_convert(ET)
        start = pd.Timestamp(now).normalize() + pd.Timedelta(hours=9, minutes=30)
        end = start + pd.Timedelta(minutes=30)
        bars = bars[~bars.index.duplicated(keep='last')].sort_index()
        return bars[(bars.index >= start) & (bars.index < end)
                    & (bars.index + pd.Timedelta(minutes=5) <= now)]

    @staticmethod
    def _complete_opening_range(bars, now):
        start = pd.Timestamp(now).normalize() + pd.Timedelta(hours=9, minutes=30)
        expected = pd.date_range(start, periods=6, freq='5min')
        return len(bars) == 6 and bars.index.equals(expected)

    def _notable_gaps(self) -> str:
        """Return string of stocks with gaps > 1%."""
        notable = [(s, g) for s, g in self.gaps.items() if abs(g) > 0.01]
        if not notable:
            return "none > 1%"
        return ", ".join(f"{s} {g*100:+.1f}%" for s, g in notable)

    # ─── Opening Range ───────────────────────────────────────────────────

    def download_opening_range_bars(self, symbols: list):
        """
        Backfill the six completed regular-session opening-range bars.
        """
        now = now_et()
        start = now.replace(hour=9, minute=30, second=0, microsecond=0)
        finish = start + timedelta(minutes=30)
        if now < finish:
            return
        start_str = start.isoformat()
        end_str = (finish - timedelta(microseconds=1)).isoformat()

        for sym in symbols:
            if self._complete_opening_range(self._opening_range_bars(sym, now), now):
                continue

            try:
                bars = self._fetch_bars(
                    sym, "5Min",
                    start=start_str, end=end_str,
                    feed="iex", limit=20, sort="asc",
                )
                if not bars:
                    continue

                for b in bars:
                    ts = _bar_timestamp(b)
                    if not (start <= ts < finish and ts + timedelta(minutes=5) <= now):
                        continue

                    existing = self.bars_5m.get(sym)
                    if existing is not None and ts in existing.index:
                        continue

                    bar_data = {
                        "Open": float(b.o), "High": float(b.h),
                        "Low": float(b.l),  "Close": float(b.c),
                        "Volume": int(b.v), "Datetime": ts,
                    }
                    self.append_bar(sym, bar_data)

            except Exception as e:
                self.log.debug(f"ORB bar download failed for {sym}: {e}")

    def compute_opening_ranges(self, symbols: list):
        """
        Compute the opening range (first 30 min high/low) for today.
        Should be called after 10:00 AM ET.
        """
        self.opening_ranges.clear()
        now = now_et()

        for sym in symbols:
            orb_bars = self._opening_range_bars(sym, now)
            if not self._complete_opening_range(orb_bars, now):
                continue
            self.opening_ranges[sym] = {
                "high": orb_bars["High"].max(),
                "low": orb_bars["Low"].min(),
            }

        self.log.info(f"Opening ranges computed for {len(self.opening_ranges)} symbols")

    # ─── Price Polling (REST fallback) ───────────────────────────────────

    def _fetch_bars(self, sym: str, timeframe: str, **kwargs):
        """Wrapper around api.get_bars with a hard timeout."""
        # A ThreadPoolExecutor context waits on exit even after result(timeout)
        # raises. Use one bounded daemon request instead, so a stuck SDK call
        # cannot freeze the scheduler or create unlimited background requests.
        if not self._fetch_lock.acquire(blocking=False):
            return []
        results = queue.Queue(maxsize=1)
        def fetch():
            try:
                results.put((True, self.api.get_bars(sym, timeframe, **kwargs)))
            except Exception as error:
                results.put((False, error))
            finally:
                self._fetch_lock.release()
        threading.Thread(target=fetch, daemon=True).start()
        try:
            ok, value = results.get(timeout=_API_TIMEOUT)
        except queue.Empty:
            self.log.warning(f"API timeout for {sym} ({timeframe}); waiting for outstanding request")
            return []
        if not ok:
            raise value
        return value

    def poll_latest_bars(self, symbols: list):
        """
        Poll latest 5-min bars via REST. Use as fallback when
        websocket is unavailable. Returns list of new bars.
        """
        new_bars = []
        now = now_et()
        cutoff = pd.Timestamp(now).floor('5min')

        for sym in symbols:
            try:
                existing = self.bars_5m.get(sym)
                last_ts = existing.index.max() if existing is not None and not existing.empty else None
                start = (last_ts + pd.Timedelta(minutes=5) if last_ts is not None
                         else pd.Timestamp(now).normalize())
                if start >= cutoff:
                    continue
                bars = self._fetch_bars(
                    sym, "5Min", start=start.isoformat(),
                    end=(cutoff - pd.Timedelta(microseconds=1)).isoformat(),
                    limit=10000, feed="iex", sort="asc",
                )
                for b in sorted(bars or [], key=_bar_timestamp):
                    ts = _bar_timestamp(b)
                    if ts < start or ts + pd.Timedelta(minutes=5) > cutoff:
                        continue

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
