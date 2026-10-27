"""
Strategy: EMA + VWAP Bearish Crossover (Intraday, 5-min) — SHORT side.

Mirror of strategy_ema_vwap for shorts. Entry when EMA(9) crosses BELOW
EMA(21) with price below EMA(55) and below VWAP, on confirming volume.
Targets and stops are ATR-based, symmetric to the long version but flipped.
"""
from math import isfinite
import config


def check_signal(row) -> str:
    """Return 'SHORT' or 'NONE'."""
    if row is None:
        return "NONE"

    ema9 = row.get("ema9")
    ema21 = row.get("ema21")
    ema55 = row.get("ema55")
    vwap_val = row.get("vwap")
    close = row.get("Close")
    volume = row.get("Volume")
    vol_ma = row.get("vol_ma")
    cross_down = row.get("ema_cross_down", False)

    if any(v is None or not isfinite(v) for v in [ema9, ema21, ema55, vwap_val, close, volume, vol_ma]):
        return "NONE"
    if vol_ma == 0:
        return "NONE"

    if not cross_down:
        return "NONE"

    # Trend filter: price below 55 EMA (downtrend)
    if close >= ema55:
        return "NONE"
    # VWAP filter: price below VWAP for shorts
    if close >= vwap_val:
        return "NONE"
    # Volume confirmation
    if volume < vol_ma * config.S1_VOLUME_THRESHOLD:
        return "NONE"
    # Don't short the bottom — reject if already too extended below EMA21
    if ema21 > 0 and (ema21 - close) / ema21 > config.EXTENSION_MAX_PCT_ABOVE_EMA21:
        return "NONE"

    return "SHORT"


def check_exit(pos, current_row) -> tuple:
    """
    Exit checks for an open SHORT position. Reasons mirror the long side.
    """
    if current_row is None:
        return False, ""

    price = current_row.get("Close", 0)
    atr_val = current_row.get("atr", 0)
    if not isfinite(price) or not isfinite(atr_val) or price <= 0 or atr_val <= 0:
        return False, ""

    entry = pos.entry_price

    # Stop-loss: ABOVE entry for shorts
    if price >= pos.stop_loss:
        return True, "stop_loss"

    # Take-profit: BELOW entry for shorts
    if pos.take_profit and price <= pos.take_profit:
        return True, "take_profit"

    # Trailing stop: track LOW water (pos.high_water reused as low_water for shorts)
    if pos.trail_activate is not None and pos.high_water is not None:
        # trail_activate for shorts = entry - X*ATR (price has dropped enough)
        if pos.high_water <= pos.trail_activate:
            trail_sl = pos.high_water + config.S1_TRAIL_STOP_ATR * atr_val
            if price >= trail_sl:
                return True, "trailing_stop"

    # Signal exit: EMA(9) crosses back above EMA(21) — trend reversal
    cross_up = current_row.get("ema_cross_up", False)
    if cross_up:
        return True, "signal_exit"

    return False, ""


def calc_stops(price, atr_val, tier_stop_mult: float = 1.0):
    """
    Stops for a SHORT: stop ABOVE entry, target BELOW entry.
    Returns (stop_loss, take_profit, trail_activate).
    """
    stop_mult = config.S1_STOP_ATR * tier_stop_mult
    sl = price + stop_mult * atr_val
    tp = price - config.S1_TP_ATR * atr_val
    trail = price - config.S1_TRAIL_ACTIVATE_ATR * atr_val
    return sl, tp, trail


def entry_details(row) -> dict:
    return {
        "strategy": "EMA_VWAP_SHORT",
        "ema9": row.get("ema9"),
        "ema21": row.get("ema21"),
        "ema55": row.get("ema55"),
        "vwap": row.get("vwap"),
        "atr": row.get("atr"),
        "volume": row.get("Volume"),
        "vol_ma": row.get("vol_ma"),
        "close": row.get("Close"),
    }
