"""
Strategy 3: Mean Reversion RSI Bounce (Swing, daily candles)
PDT SAFE — holds positions overnight.
LONG ONLY.
"""
import numpy as np
import config


def check_signal(daily_row) -> str:
    """
    Check if daily candle produces an RSI bounce entry signal.
    Returns "BUY" or "NONE".
    """
    if daily_row is None:
        return "NONE"

    rsi_val = daily_row.get("rsi7")
    close = daily_row.get("Close")
    bb_lower = daily_row.get("bb_lower")
    sma50 = daily_row.get("sma50")

    if any(v is None for v in [rsi_val, close, bb_lower, sma50]):
        return "NONE"

    # Check for NaN
    if any(np.isnan(v) for v in [rsi_val, close, bb_lower, sma50]):
        return "NONE"

    # BUY: RSI < 25, price near lower BB (within 1%), price above 50 SMA
    if (rsi_val < config.S3_RSI_OVERSOLD and
            close <= bb_lower * 1.01 and
            close > sma50):
        return "BUY"

    return "NONE"


def check_exit(pos, daily_row, bars_held: int) -> tuple:
    """
    Check exit conditions for an RSI bounce position.
    Returns (should_exit: bool, reason: str).

    bars_held: number of trading days held.
    """
    if daily_row is None:
        return False, ""

    price = daily_row.get("Close", 0)
    rsi_val = daily_row.get("rsi7", 50)
    bb_mid = daily_row.get("bb_mid")
    entry = pos.entry_price

    if price == 0:
        return False, ""

    # Take-profit: RSI > 55
    if rsi_val is not None and not np.isnan(rsi_val) and rsi_val > config.S3_RSI_EXIT:
        return True, "rsi_exit"

    # Take-profit: price hits middle Bollinger Band
    if bb_mid is not None and not np.isnan(bb_mid) and price >= bb_mid:
        return True, "bb_mid_exit"

    # Stop-loss: 2% below entry
    if price <= entry * (1 - config.S3_STOP_LOSS_PCT):
        return True, "stop_loss"

    # Time stop: 5 trading days
    if bars_held >= config.S3_MAX_HOLD_DAYS:
        return True, "time_stop"

    return False, ""


def calc_stops(price):
    """
    Calculate stop-loss for an RSI bounce LONG.
    Returns stop_loss price.
    """
    return price * (1 - config.S3_STOP_LOSS_PCT)


def entry_details(daily_row) -> dict:
    """Return indicator snapshot for the trade explainer."""
    return {
        "strategy": "RSI_BOUNCE",
        "rsi7": daily_row.get("rsi7"),
        "bb_lower": daily_row.get("bb_lower"),
        "bb_mid": daily_row.get("bb_mid"),
        "bb_upper": daily_row.get("bb_upper"),
        "sma50": daily_row.get("sma50"),
        "close": daily_row.get("Close"),
    }
