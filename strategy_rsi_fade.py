"""
Strategy: RSI Fade (Swing, daily candles) — SHORT side.

Mirror of strategy_rsi (RSI bounce). Short overbought exhaustion:
  RSI(7) > 75 + price near upper Bollinger Band + price below SMA(50)
  (the SMA filter ensures we're shorting INTO an existing downtrend,
  not against a strong uptrend — that's a key edge vs naive overbought shorting.)

PDT-safe: holds positions overnight.
"""
import numpy as np
import config


def check_signal(daily_row) -> str:
    """Return 'SHORT' or 'NONE'."""
    if daily_row is None:
        return "NONE"

    rsi_val = daily_row.get("rsi7")
    close = daily_row.get("Close")
    bb_upper = daily_row.get("bb_upper")
    sma50 = daily_row.get("sma50")

    if any(v is None for v in [rsi_val, close, bb_upper, sma50]):
        return "NONE"
    if any(np.isnan(v) for v in [rsi_val, close, bb_upper, sma50]):
        return "NONE"

    # SHORT: RSI > 75, price near upper BB (within 1%), and price < SMA50
    # (in a downtrend or sideways — not fighting strong uptrend)
    if (rsi_val > config.SHORT_RSI_OVERBOUGHT and
            close >= bb_upper * 0.99 and
            close < sma50):
        return "SHORT"

    return "NONE"


def check_exit(pos, daily_row, bars_held: int) -> tuple:
    """Exit checks for an RSI_FADE short."""
    if daily_row is None:
        return False, ""

    price = daily_row.get("Close", 0)
    rsi_val = daily_row.get("rsi7", 50)
    bb_mid = daily_row.get("bb_mid")
    entry = pos.entry_price
    if price == 0:
        return False, ""

    # Cover-profit: RSI falls back to neutral
    if rsi_val is not None and not np.isnan(rsi_val) and rsi_val < config.SHORT_RSI_EXIT:
        return True, "rsi_exit"

    # Cover-profit: price crashes through BB midline (target met)
    if bb_mid is not None and not np.isnan(bb_mid) and price <= bb_mid:
        return True, "bb_mid_exit"

    # Stop-loss: 2% ABOVE entry (loss when shorts rally)
    if price >= entry * (1 + config.SHORT_STOP_PCT_MIN):
        return True, "stop_loss"

    # Time stop: same 5-day rule as long bounce
    if bars_held >= config.S3_MAX_HOLD_DAYS:
        return True, "time_stop"

    return False, ""


def calc_stops(price):
    """Stop for an RSI_FADE short: 2% above entry."""
    return price * (1 + config.SHORT_STOP_PCT_MIN)


def entry_details(daily_row) -> dict:
    return {
        "strategy": "RSI_FADE",
        "rsi7": daily_row.get("rsi7"),
        "bb_lower": daily_row.get("bb_lower"),
        "bb_mid": daily_row.get("bb_mid"),
        "bb_upper": daily_row.get("bb_upper"),
        "sma50": daily_row.get("sma50"),
        "close": daily_row.get("Close"),
    }
