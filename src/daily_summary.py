"""Account-scoped closing reports from broker history, independent of engine uptime."""
import asyncio
import hashlib
import json
import math
import os
import tempfile
from datetime import datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')

def finite(value):
    value=float(value)
    if not math.isfinite(value):raise ValueError('Invalid summary value')
    return value

async def closing_report(broker,values,directory,now=None):
    now=now or datetime.now(ET)
    account_id=values.get('paper_account_id')
    if not account_id:return dict(report=None,detail='Connect a paper account to load closing summaries.')
    rows=await broker('/v2/calendar',values,params=dict(start=(now.date()-timedelta(days=14)).isoformat(),end=now.date().isoformat()))
    completed=[]
    for row in rows:
        close=datetime.combine(datetime.fromisoformat(row['date']).date(),time.fromisoformat(row['close']),ET)
        if now>=close+timedelta(minutes=5):completed.append((row['date'],close))
    if not completed:return dict(report=None,detail='Waiting for a completed exchange session.')
    day,close=max(completed)
    scope=hashlib.sha256(account_id.encode()).hexdigest()[:24]
    path=Path(directory)/('closing-'+scope+'-'+day+'.json')
    if path.exists():
        try:
            saved=json.loads(path.read_text())
            if saved['account_id']==account_id and saved['date']==day:return dict(report=saved)
        except (ValueError,KeyError):pass
    account,history=await asyncio.gather(broker('/v2/account',values),
        broker('/v2/account/portfolio/history',values,params=dict(
            start=datetime.combine(close.date(),time(0),ET).isoformat(),
            end=close.isoformat(),timeframe='5Min',intraday_reporting='market_hours',pnl_reset='per_day')))
    if account.get('id')!=account_id:raise ValueError('Broker account no longer matches the saved connection')
    stamps=history.get('timestamp') or [];equities=history.get('equity') or [];pnl=history.get('profit_loss') or []
    if not(len(stamps)==len(equities)==len(pnl)):raise ValueError('Incomplete broker closing history')
    points=[]
    for stamp,equity,profit in zip(stamps,equities,pnl):
        if equity is None or profit is None:continue
        observed=datetime.fromtimestamp(finite(stamp),ET)
        if observed.date()==close.date() and close-timedelta(minutes=10)<=observed<=close:
            points.append((finite(stamp),finite(equity),finite(profit)))
    if not points:return dict(report=None,detail='Broker closing history is not available yet. It will be retried automatically.')
    fills=[];token=None;seen=set()
    for _ in range(100):
        params=dict(date=day,direction='asc',page_size=100)
        if token:params['page_token']=token
        page=await broker('/v2/account/activities/FILL',values,params=params)
        fills.extend(page)
        if len(page)<100:break
        token=page[-1]['id']
        if token in seen:raise ValueError('Broker fill pagination did not advance')
        seen.add(token)
    else:raise ValueError('Broker fill history exceeds report limit')
    opening=next(row['open'] for row in rows if row['date']==day)
    opened=datetime.combine(close.date(),time.fromisoformat(opening),ET)
    fills=[f for f in fills if opened<=datetime.fromisoformat(f['transaction_time'].replace('Z','+00:00'))<=close]
    _,equity,profit=max(points)
    report=dict(account_id=account_id,date=day,session_close=close.isoformat(),
        generated_at=now.isoformat(),closing_equity=equity,account_pnl=profit,
        filled_orders=len({f['order_id'] for f in fills}),fills=len(fills),
        buy_volume=sum(finite(f['qty'])*finite(f['price']) for f in fills if f['side']=='buy'),
        sell_volume=sum(finite(f['qty'])*finite(f['price']) for f in fills if f['side']=='sell'),
        symbols=sorted({f['symbol'] for f in fills}),
        detail='Regular-session account P&L includes realized and unrealized changes across strategies and manual trades. Filled orders are not closed round trips.')
    path.parent.mkdir(parents=True,exist_ok=True)
    fd,temp=tempfile.mkstemp(dir=str(path.parent),prefix='.closing-',suffix='.tmp')
    try:
        with os.fdopen(fd,'w') as handle:
            json.dump(report,handle,allow_nan=False);handle.flush();os.fsync(handle.fileno())
        os.replace(temp,path)
    finally:
        if os.path.exists(temp):os.unlink(temp)
    return dict(report=report)
