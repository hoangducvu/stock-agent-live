"""
Strategy 2: Opening Range Breakout (Intraday, 5-min candles)
LONG ONLY (short selling disabled for $100 account).
"""
import config


def check_signal(row, opening_range: dict, daily_row=None) -> str:
    """
    Check if current bar breaks out of the opening range.
    Returns "BUY" or "NONE".

    row: latest 5-min indicator row
    opening_range: {"high": float, "low": float}
    daily_row: latest daily indicator row (for trend filter)
    """
    if row is None or opening_range is None:
        return "NONE"

    close = row.get("Close")
    volume = row.get("Volume")
    vol_ma = row.get("vol_ma")
    orb_high = opening_range.get("high")
    orb_low = opening_range.get("low")

    if any(v is None for v in [close, volume, orb_high, orb_low]):
        return "NONE"

    # Volume confirmation: >= 1.5x average
    if vol_ma and vol_ma > 0:
        if volume < vol_ma * config.S2_VOLUME_THRESHOLD:
            return "NONE"

    # Trend filter from daily EMA (if available)
    if daily_row is not None:
        ema20 = daily_row.get("ema20")
        daily_close = daily_row.get("Close")
        if ema20 is not None and daily_close is not None:
            # For longs: daily close should be above EMA20
            if daily_close < ema20 and close > orb_high:
                return "NONE"  # bearish daily trend, skip long breakout

    # LONG breakout: close above opening range high
    if close > orb_high:
        return "BUY"

    # ── SHORT breakdown (disabled for $100 account) ──
    # if close < orb_low:
    #     return "SELL"

    return "NONE"


def check_exit(pos, current_row, opening_range: dict) -> tuple:
    """
    Check exit conditions for an ORB position.
    Returns (should_exit: bool, reason: str).
    """
    if current_row is None or opening_range is None:
        return False, ""

    price = current_row.get("Close", 0)
    orb_high = opening_range.get("high", 0)
    orb_low = opening_range.get("low", 0)
    orb_width = orb_high - orb_low

    if price == 0 or orb_width == 0:
        return False, ""

    entry = pos.entry_price

    # For LONG positions:
    # Stop-loss: at ORB low (opposite side of range)
    if price <= orb_low:
        return True, "stop_loss"

    # Take-profit: entry + 2x ORB width
    tp = entry + 2 * orb_width
    if price >= tp:
        return True, "take_profit"

    return False, ""


def calc_stops(price, opening_range: dict):
    """
    Calculate stop-loss and take-profit for a LONG ORB trade.
    Returns (stop_loss, take_profit).
    """
    orb_high = opening_range.get("high", price)
    orb_low = opening_range.get("low", price)
    orb_width = orb_high - orb_low

    sl = orb_low  # stop at opposite side
    tp = price + 2 * orb_width  # target 2x width
    return sl, tp


def entry_details(row, opening_range: dict) -> dict:
    """Return indicator snapshot for the trade explainer."""
    return {
        "strategy": "ORB",
        "orb_high": opening_range.get("high"),
        "orb_low": opening_range.get("low"),
        "orb_width": opening_range.get("high", 0) - opening_range.get("low", 0),
        "close": row.get("Close"),
        "volume": row.get("Volume"),
        "vol_ma": row.get("vol_ma"),
    }
