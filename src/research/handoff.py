"""Import worker-fetched watchlist bars into the EXISTING DataFeed; no I/O waits."""
from datetime import datetime, timezone
import os
from .calendar import ET
from .config import ResearchConfig, runtime_policy
from .db import ResearchDB

def merge_watchlist(feed,db_path,scope,now=None):
    if os.getenv('NEXLARA_MANAGED_AI')=='true':
        if not runtime_policy().enabled:return []
    elif os.getenv('AI_ENABLED','false').lower()!='true':return []
    import pandas as pd
    now=now or datetime.now(timezone.utc);day=now.astimezone(ET).date().isoformat();db=ResearchDB(db_path)
    watch=db.get('watchlist',scope+':'+day) or {};ready=[]
    for symbol in watch:
        prepared=db.get('watch_bars',scope+':'+day+':'+symbol)
        if not prepared:continue
        ready.append(symbol)
        # Do not replace bars already updated by the original live data feed.
        if symbol in feed.indicators_5m and symbol in feed.indicators_daily:continue
        intraday=pd.DataFrame(prepared['intraday']).rename(columns=dict(o='Open',h='High',l='Low',c='Close',v='Volume'))
        intraday['Datetime']=pd.to_datetime(intraday['t'],utc=True).dt.tz_convert(ET)
        feed.bars_5m[symbol]=intraday.drop(columns=['t']).set_index('Datetime').sort_index()
        daily=pd.DataFrame(prepared['daily']).rename(columns=dict(o='Open',h='High',l='Low',c='Close',v='Volume'))
        daily['Date']=pd.to_datetime(daily['t'],utc=True).dt.tz_convert(ET).dt.tz_localize(None).dt.normalize()
        feed.bars_daily[symbol]=daily.drop(columns=['t']).set_index('Date').sort_index()
        feed.last_prices[symbol]=float(feed.bars_5m[symbol]['Close'].iloc[-1])
        feed.compute_indicators([symbol])
    return ready
