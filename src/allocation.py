"""Deterministic allocation from fresh broker state, including margin horizons."""
import math
from scalp_exits import INTRADAY

def field(row,name,default=None):
    return row.get(name,default) if isinstance(row,dict) else getattr(row,name,default)

def number(value):
    value=float(value)
    if not math.isfinite(value):raise ValueError('Invalid broker allocation value')
    return value

def allocation_capacity(account,positions,orders,strategy,max_positions,max_exposure,reserve_pct):
    equity=number(field(account,'equity'));bp=number(field(account,'buying_power'))
    if equity<=0 or bp<0:raise ValueError('Invalid account equity/buying power')
    held={field(p,'symbol'):p for p in positions}
    if None in held:raise ValueError('Position symbol missing')
    exposure=sum(abs(number(field(p,'market_value'))) for p in positions)
    pending_symbols=set()
    for order in orders:
        symbol=field(order,'symbol');side=field(order,'side')
        if not symbol or side not in {'buy','sell'}:raise ValueError('Invalid pending order')
        qty=field(order,'qty')
        remaining=max(0,number(qty or 0)-number(field(order,'filled_qty',0) or 0))
        position=held.get(symbol)
        if position and ((field(position,'side')=='short' and side=='buy') or (field(position,'side')!='short' and side=='sell')):
            if qty is None:raise ValueError('Unknown closing order quantity')
            remaining=max(0,remaining-abs(number(field(position,'qty'))))
            if remaining==0:continue
        price=field(order,'limit_price') or field(order,'stop_price')
        value=remaining*number(price) if qty is not None and price else number(field(order,'notional',0) or 0)
        if value<=0:raise ValueError('Unknown pending order exposure')
        exposure+=value;pending_symbols.add(symbol)
    slots=max(0,max_positions-len(set(held)|pending_symbols))
    buffer=1-reserve_pct/100
    multiplier=number(field(account,'multiplier',1))
    # Capacity uses broker buying power plus an independent gross exposure ceiling.
    ceiling=equity*min(max_exposure,max(1,multiplier))
    capacity=min(bp*buffer,max(0,ceiling*buffer-exposure))
    if strategy not in INTRADAY:
        regt=field(account,'regt_buying_power')
        if regt is None:raise ValueError('Overnight buying power unavailable')
        capacity=min(capacity,max(0,number(regt))*buffer,max(0,equity*min(max(1,multiplier),2)*buffer-exposure))
    if capacity<0 or not math.isfinite(capacity):raise ValueError('Invalid allocation capacity')
    return dict(capacity=capacity,slots=slots,exposure=exposure)

def allocation_budget(state,order_cap):
    if state['slots']<=0:return 0.0
    return min(order_cap,state['capacity']/state['slots'])
