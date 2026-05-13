"""
Strategy 1: EMA + VWAP Crossover Momentum (Intraday, 5-min candles)
LONG ONLY (short selling disabled for $100 account).
"""
import config


def check_signal(row) -> str:
    """
    Check if latest 5-min bar produces an entry signal.
    Returns "BUY" or "NONE".
    row: pandas Series with indicator columns from DataFeed.
    """
    if row is None:
        return "NONE"

    ema9 = row.get("ema9")
    ema21 = row.get("ema21")
    ema55 = row.get("ema55")
    vwap_val = row.get("vwap")
    close = row.get("Close")
    volume = row.get("Volume")
    vol_ma = row.get("vol_ma")
    cross_up = row.get("ema_cross_up", False)

    # Need all indicators computed
    if any(v is None for v in [ema9, ema21, ema55, vwap_val, close, volume, vol_ma]):
        return "NONE"
    if vol_ma == 0:
        return "NONE"

    # LONG signal: 9 EMA crosses above 21 EMA
    if cross_up:
        # Trend filter: price above 55 EMA
        if close <= ema55:
            return "NONE"

        # VWAP filter: price above VWAP for longs
        if close <= vwap_val:
            return "NONE"

        # Volume filter: >= 1.2x average
        if volume < vol_ma * config.S1_VOLUME_THRESHOLD:
            return "NONE"

        return "BUY"

    # ── SHORT signal (disabled for $100 account) ──
    # cross_down = row.get("ema_cross_down", False)
    # if cross_down:
    #     if close >= ema55:
    #         return "NONE"
    #     if close >= vwap_val:
    #         return "NONE"
    #     if volume < vol_ma * config.S1_VOLUME_THRESHOLD:
    #         return "NONE"
    #     return "SELL"

    return "NONE"


def check_exit(pos, current_row) -> tuple:
    """
    Check exit conditions for an open EMA_VWAP position.
    Returns (should_exit: bool, reason: str).
    """
    if current_row is None:
        return False, ""

    price = current_row.get("Close", 0)
    atr_val = current_row.get("atr", 0)

    if price == 0 or atr_val == 0:
        return False, ""

    entry = pos.entry_price

    # 1. Stop-loss: 1.5x ATR below entry
    sl = entry - config.S1_STOP_ATR * atr_val
    if price <= sl:
        return True, "stop_loss"

    # 2. Take-profit: 2.5x ATR above entry
    tp = entry + config.S1_TP_ATR * atr_val
    if price >= tp:
        return True, "take_profit"

    # 3. Trailing stop
    if pos.trail_activate is not None and pos.high_water is not None:
        if price >= pos.trail_activate:
            trail_sl = pos.high_water - config.S1_TRAIL_STOP_ATR * atr_val
            if price <= trail_sl:
                return True, "trailing_stop"

    # 4. Signal exit: 9 EMA crosses back below 21 EMA
    cross_down = current_row.get("ema_cross_down", False)
    if cross_down:
        return True, "signal_exit"

    return False, ""


def calc_stops(price, atr_val):
    """
    Calculate stop-loss, take-profit, and trailing activation for a LONG.
    Returns (stop_loss, take_profit, trail_activate).
    """
    sl = price - config.S1_STOP_ATR * atr_val
    tp = price + config.S1_TP_ATR * atr_val
    trail = price + config.S1_TRAIL_ACTIVATE_ATR * atr_val
    return sl, tp, trail


def entry_details(row) -> dict:
    """Return indicator snapshot for the trade explainer."""
    return {
        "strategy": "EMA_VWAP",
        "ema9": row.get("ema9"),
        "ema21": row.get("ema21"),
        "ema55": row.get("ema55"),
        "vwap": row.get("vwap"),
        "atr": row.get("atr"),
        "volume": row.get("Volume"),
        "vol_ma": row.get("vol_ma"),
        "close": row.get("Close"),
    }
