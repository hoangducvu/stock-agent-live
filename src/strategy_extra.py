"""Additional long intraday signals; exits use the shared ATR lifecycle."""
from math import isfinite

def values(row, names):
    if row is None: return None
    out = [row.get(n) for n in names]
    try:
        return out if all(v is not None and isfinite(v) for v in out) else None
    except TypeError:
        return None

def pullback(row):
    v = values(row, ['Close','Low','ema9','ema21','ema55','vwap','Volume','vol_ma','previous_close'])
    if v is None: return 'NONE'
    close, low, fast, slow, trend, vwap, volume, avg_volume, previous = v
    return 'BUY' if (close > 0 and fast > slow > trend and close > fast and close > vwap and
                     low <= fast and previous <= fast and avg_volume > 0 and volume >= avg_volume * 1.2) else 'NONE'

def channel_breakout(row):
    v = values(row, ['Close','previous_close','prior_high20','ema55','vwap','Volume','vol_ma'])
    if v is None: return 'NONE'
    close, previous, high, trend, vwap, volume, avg_volume = v
    return 'BUY' if (high > 0 and close > high >= previous and close > trend and close > vwap and
                     avg_volume > 0 and volume >= avg_volume * 1.5) else 'NONE'

def news_momentum(row):
    v = values(row, ['Open','Close','ema9','ema21','vwap','Volume','vol_ma'])
    if v is None: return 'NONE'
    opening, close, fast, slow, vwap, volume, avg_volume = v
    return 'BUY' if (close > opening > 0 and close > fast > slow and close > vwap and
                     avg_volume > 0 and volume >= avg_volume * 1.5) else 'NONE'


def fresh_intraday(row, now):
    if row is None: return False
    try:
        stamp = row.name
        age = (now - stamp).total_seconds()
        return stamp.tzinfo is not None and 0 <= age <= 15 * 60
    except (AttributeError, TypeError, ValueError):
        return False
