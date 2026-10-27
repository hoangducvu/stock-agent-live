"""Optional daily trend-following strategy; never replaces existing strategies."""
from math import isfinite
from datetime import datetime

def check_signal(row):
    if row is None:return 'NONE'
    try:
        price,ma50,ma200,rsi,momentum,atr=[float(row[k]) for k in ('Close','sma50','sma200','rsi14','momentum20','atr14')]
        return 'BUY' if all(isfinite(v) for v in (price,ma50,ma200,rsi,momentum,atr)) and price>ma50>ma200>0 and 40<=rsi<=70 and momentum>0 and 0<atr/price<=.08 else 'NONE'
    except (KeyError,TypeError,ValueError):return 'NONE'

def check_exit(position,row,now,min_hold,max_hold):
    if row is None:return False,''
    price=float(row.get('Close',0))
    if not isfinite(price) or price<=0:return False,''
    if price<=position.stop_loss:return True,'stop_loss'
    age=(now.date()-datetime.fromisoformat(position.entry_time).date()).days
    if age>=max_hold:return True,'time_stop'
    if age>=min_hold and price<float(row.get('sma50',0)):return True,'trend_deterioration'
    return False,''
