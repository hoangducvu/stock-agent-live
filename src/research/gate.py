"""Nonblocking entry interface. Model calls happen ONLY in the separate worker."""
from datetime import datetime, timezone
import math
import os
from pathlib import Path
from .calendar import ET
from .config import ResearchConfig, runtime_policy
from .db import ResearchDB
from .service import fingerprint

def db_path():return os.getenv('NEXLARA_RESEARCH_DB',str(Path(__file__).resolve().parents[1]/'data'/'research.sqlite3'))
def scope():return os.getenv('NEXLARA_ACCOUNT_SCOPE','unconfigured')
def setup_key(symbol,strategy,price,watch,day):
    anchor=float(watch.get('price') or price)
    # 1% price movement, new report/news/regime, or changed strategy invalidates.
    return fingerprint(dict(scope=scope(),ticker=symbol,strategy=strategy,day=day,
        price_band=round(price/anchor*100),version=watch.get('snapshot_version'),regime=watch.get('regime'),model=runtime_policy().model))
def permit_entry(symbol,strategy,price,qty,now=None):
    if os.getenv('NEXLARA_MANAGED_AI')=='true':
        config=runtime_policy()
        if not config.enabled:return True,None,'AI disabled or no saved API key; original signal/risk path'
    else:
        enabled=os.getenv('AI_ENABLED','false').lower()
        if enabled=='false':return True,None,'AI disabled; original signal/risk path'
        if enabled!='true':return False,None,'Invalid AI_ENABLED configuration'
        config=ResearchConfig.from_env()
    if os.getenv('TRADING_MODE','paper')!='paper':return False,None,'AI entries require paper trading'
    from scalp_exits import INTRADAY
    if config.prototype and strategy in INTRADAY:return True,None,'Prototype: intraday uses original deterministic execution/risk path'
    now=now or datetime.now(timezone.utc);day=now.astimezone(ET).date().isoformat()
    db=ResearchDB(db_path());keyday=scope()+':'+day
    if config.prototype and db.usage(day)['cost']>=config.dollars:return False,None,'Daily AI budget exhausted'
    session=db.get('session',keyday)
    if not session or not datetime.fromisoformat(session['entry'])<=now<datetime.fromisoformat(session['close']):return False,None,'Outside AI entry window or calendar unavailable'
    watch=db.get('watchlist',keyday) or {}
    row=watch.get(symbol)
    if row is None:
        if not config.allow_additional:return False,None,'Not on approved watchlist'
        row=db.get('screened',scope()+':'+symbol)
        if not row:return False,None,'Additional candidate lacks screened evidence'
    key=setup_key(symbol,strategy,price,row,day)
    payload=dict(ticker=symbol,strategy=strategy,price=price,qty=qty,scope=scope(),watch=row,
                 signal_timestamp=now.isoformat(),snapshot_version=row.get('snapshot_version'),model=config.model)
    db.queue_signal(key,day,symbol,strategy,payload)
    if not config.validation:
        # Screening-only comparison mode still needs deterministic quote/exposure checks.
        decision={'action':'BUY'}
    else:decision=db.get('entry_decision',key,now.timestamp())
    checks=db.get('entry_check',key,now.timestamp())
    if not decision or decision.get('action')!='BUY' or not checks or not checks.get('allowed'):
        db.event('entry_denied',key,dict(ticker=symbol,reason='Pending, expired, denied AI decision or deterministic checks'))
        return False,None,'Research validation pending or denied'
    quote=float(checks['price']);spread=float(checks['spread_bps'])
    if not math.isfinite(quote) or quote<=0 or abs(price/quote-1)*10000>config.max_slippage_bps or spread>config.max_spread_bps:return False,None,'Price moved since validated quote'
    # Reserve the maximum actual proposed value, not a model-generated size.
    if price*qty>float(checks['max_notional'])+1e-8:return False,None,'Proposed exposure changed since validation'
    intent='nx-'+key[:40]
    payload.update(sector=row.get('sector'),reserved_notional=price*qty*1.01)
    if not db.reserve_entry(intent,payload,checks):return False,None,'Duplicate/ambiguous setup or reserved exposure limit'
    db.event('entry_permitted',intent,dict(ticker=symbol,strategy=strategy))
    return True,intent,'Approved advisory plus deterministic checks'

def record_execution(client_id,result):
    if not client_id:return
    db=ResearchDB(db_path())
    db.order_result(client_id,'filled' if result and result.get('filled') else 'unfilled_or_unresolved',
        (result or {}).get('order_id'),result or {})

def deterministic_entry(snapshot,portfolio,watch,config,notional,now):
    """Fail closed on missing quote/earnings/sector/portfolio evidence."""
    reasons=[]
    try:
        quote=snapshot['latestQuote'];bid=float(quote['bp']);ask=float(quote['ap'])
        timestamp=datetime.fromisoformat(quote['t'].replace('Z','+00:00'))
        if timestamp.tzinfo is None or not 0<bid<=ask or not 0<=(now-timestamp).total_seconds()<=60:reasons.append('stale_or_invalid_quote')
        mid=(bid+ask)/2;spread=(ask-bid)/mid*10000
        if spread>config.max_spread_bps:reasons.append('spread')
        if config.prototype and watch.get('research_anchor_price') and abs(mid/float(watch['research_anchor_price'])-1)>=.05:reasons.append('company_research_price_changed')
        account=portfolio['account'];equity=float(account['equity']);buying_power=float(account['buying_power'])
        if config.allocation_mode=='fill_slots':
            from allocation import allocation_capacity
            allocation=allocation_capacity(account,portfolio['positions'],portfolio.get('pending_orders',[]),watch.get('strategy','TREND_SWING'),config.max_positions,config.max_exposure,config.buying_power_reserve_pct)
            if allocation['slots']<=0 or notional>allocation['capacity']:reasons.append('allocation_or_overnight_capacity')
        if equity<=0 or buying_power<notional or account.get('status')!='ACTIVE':reasons.append('account')
        exposure=sum(abs(float(p['market_value'])) for p in portfolio['positions'])
        if (exposure+notional)/equity>config.max_exposure:reasons.append('portfolio_exposure')
        if not watch.get('sector'):reasons.append('missing_sector')
        sectors=portfolio.get('sectors',{})
        sector_exposure=0
        for position in portfolio['positions']:
            sector=sectors.get(position['symbol'])
            if sector is None:reasons.append('missing_position_sector')
            if sector==watch.get('sector'):sector_exposure+=abs(float(position['market_value']))
        for order in portfolio.get('pending_orders',[]):
            symbol=order['symbol'];side=order['side']
            remaining=max(0,float(order.get('qty') or 0)-float(order.get('filled_qty') or 0))
            held=next((p for p in portfolio['positions'] if p['symbol']==symbol),None)
            if held and ((held.get('side')=='short' and side=='buy') or (held.get('side')!='short' and side=='sell')):
                remaining=max(0,remaining-abs(float(held['qty'])))
                if remaining==0:continue
            order_price=float(order.get('limit_price') or order.get('stop_price') or 0)
            pending_value=float(order.get('notional') or 0) if not order.get('qty') else remaining*order_price
            if pending_value<=0:
                reasons.append('unknown_pending_order_exposure');continue
            sector=sectors.get(symbol)
            if sector is None:reasons.append('missing_pending_order_sector')
            exposure+=pending_value
            if sector==watch.get('sector'):sector_exposure+=pending_value
        if (exposure+notional)/equity>config.max_exposure:reasons.append('portfolio_pending_exposure')
        if (sector_exposure+notional)/equity>config.max_sector:reasons.append('sector_exposure')
        if watch['average_dollar_volume']<config.min_dollar_volume or watch['atr_pct']>config.max_atr_pct:reasons.append('liquidity_or_volatility')
        if config.require_fundamentals and not watch.get('fundamentals'):reasons.append('missing_fundamentals')
        earnings=watch.get('next_earnings')
        if config.require_earnings and not earnings:reasons.append('missing_earnings')
        if earnings and (datetime.fromisoformat(earnings).date()-now.astimezone(ET).date()).days<=config.earnings_buffer_days:reasons.append('earnings_risk')
        if any(p['symbol']==watch['ticker'] for p in portfolio['positions']):reasons.append('already_held')
        if snapshot.get('trading_status','active')!='active':reasons.append('trading_status')
        if not all(math.isfinite(v) for v in (mid,spread,equity,buying_power,notional)) or notional<=0:reasons.append('invalid_numeric_data')
    except (KeyError,TypeError,ValueError,ZeroDivisionError):
        return dict(allowed=False,reasons=['missing_or_invalid_broker_data'])
    return dict(allowed=not reasons,reasons=reasons,price=mid,spread_bps=spread,max_notional=notional,
                portfolio_room=max(0,config.max_exposure*equity-exposure),sector_room=max(0,config.max_sector*equity-sector_exposure),
                broker_symbols=[p['symbol'] for p in portfolio['positions']])
