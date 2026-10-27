"""Deterministic intraday exits; no AI calls or broker mutations here."""
from datetime import datetime
from math import isfinite
from zoneinfo import ZoneInfo
import config

INTRADAY = frozenset({'EMA_VWAP','ORB','EMA_PULLBACK','DONCHIAN','NEWS_MOMENTUM','EMA_VWAP_SHORT'})

def positive(value):
    try:return isfinite(float(value)) and float(value)>0
    except (TypeError,ValueError):return False

def calc_stops(price, atr, side='long'):
    if not positive(price) or not positive(atr):raise ValueError('Valid price and ATR required')
    direction=1 if side=='long' else -1
    stop=price-direction*config.SCALP_STOP_ATR*atr
    if stop<=0:raise ValueError('Invalid scalp stop')
    return stop, None, price+direction*config.SCALP_TRAIL_ACTIVATE_ATR*atr

def check_exit(pos,row,now):
    if pos.strategy not in INTRADAY:return False,''
    # Time exit is independent of indicator availability and AI.
    try:
        entered=datetime.fromisoformat(pos.entry_time)
        if entered.tzinfo is None:entered=entered.replace(tzinfo=ZoneInfo('America/New_York'))
        if (now-entered).total_seconds()>=config.SCALP_MAX_HOLD_MINUTES*60:
            return True,'scalp_max_hold'
    except (ValueError,TypeError):
        # Unknown ownership timestamps must not be invented.
        pass
    if row is None or not positive(row.get('Close')):return False,''
    price=float(row['Close']);short=pos.side=='short'
    if positive(pos.stop_loss) and (price>=pos.stop_loss if short else price<=pos.stop_loss):
        return True,'scalp_stop'
    # Use directional EMA state, not a one-bar crossover that may be missed.
    fast,slow=row.get('ema9'),row.get('ema21')
    if positive(fast) and positive(slow) and (fast>slow if short else fast<slow):
        return True,'scalp_momentum_reversal'
    atr=row.get('atr')
    if not positive(atr):return False,''
    water=pos.high_water if positive(pos.high_water) else pos.entry_price
    pos.high_water=min(water,price) if short else max(water,price)
    trigger=pos.trail_activate
    if positive(trigger) and (pos.high_water<=trigger if short else pos.high_water>=trigger):
        proposed=pos.high_water+(1 if short else -1)*config.SCALP_TRAIL_ATR*atr
        # Ratchet only: rising volatility must never loosen a tightened stop.
        if positive(proposed):
            pos.stop_loss=min(pos.stop_loss,proposed) if short else max(pos.stop_loss,proposed)
        if price>=pos.stop_loss if short else price<=pos.stop_loss:
            return True,'scalp_trailing_stop'
    return False,''
