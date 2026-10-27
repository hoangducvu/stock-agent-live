"""Private single-user dashboard API. No broker keys are returned to browsers."""
import asyncio
import math
from pathlib import Path
import httpx
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from typing import Literal, Optional
from backend.settings_store import SettingsStore
from strategy_catalog import CATALOG, IDS, SHORT_IDS

router = APIRouter(prefix='/api/workspace')
store = SettingsStore(Path(__file__).parent.parent / 'data')
control_lock = asyncio.Lock()
BASE = 'https://paper-api.alpaca.markets'
DATA = 'https://data.alpaca.markets'

class Settings(BaseModel):
    api_key: Optional[str] = Field(default=None, min_length=1, max_length=256)
    secret_key: Optional[str] = Field(default=None, min_length=1, max_length=256)
    strategy: Literal['ema_vwap', 'orb', 'rsi'] = 'ema_vwap'
    strategies: Optional[list[str]] = None
    shorts_enabled: bool = True
    news_enabled: bool = True
    position_size_multiplier: float = Field(default=10, ge=1, le=20, allow_inf_nan=False)
    max_order_value: float = Field(default=10000, ge=1, le=10000, allow_inf_nan=False)
    max_position_pct: float = Field(default=5, ge=.1, le=10, allow_inf_nan=False)
    max_daily_loss_pct: float = Field(default=2, ge=.1, le=5, allow_inf_nan=False)
    max_positions: int = Field(default=20, ge=1, le=50)
    allocation_mode: Literal['percentage','fill_slots'] = 'fill_slots'
    buying_power_reserve_pct: float = Field(default=5,ge=1,le=50,allow_inf_nan=False)
    max_gross_exposure_pct: float = Field(default=400,ge=10,le=400,allow_inf_nan=False)
    starting_capital: float = Field(default=5000, ge=10, le=1000000, allow_inf_nan=False)
    halt_equity: float = Field(default=4500, ge=0, le=1000000, allow_inf_nan=False)
    ai_model: Optional[str] = Field(default=None,max_length=120)
    ai_enabled: bool = False
    ai_api_key: Optional[str] = Field(default=None, max_length=512)
    slack_notifications: bool = False
    slack_webhook: Optional[str] = Field(default=None, max_length=512)
    slack_channel: str = Field(default='', max_length=80)
    close_on_stop: bool = True

async def broker(path, values, data=False, params=None):
    if not values.get('api_key') or not values.get('secret_key'):
        raise HTTPException(409, 'Save your Alpaca paper API key and secret in Settings first.')
    try:
        async with httpx.AsyncClient(timeout=12) as client:
            r = await client.get((DATA if data else BASE)+path, params=params, headers={
                'APCA-API-KEY-ID': values['api_key'], 'APCA-API-SECRET-KEY': values['secret_key']})
        if r.status_code in (401,403):
            detail = ('Market-data access denied for the saved keys.' if data else
                      'Paper account authentication failed. Replace BOTH the API key and its matching secret; live-account keys do not work here.')
            raise HTTPException(409, detail)
        r.raise_for_status()
        return r.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Broker request failed. Check connectivity and retry; no order was submitted.')

@router.get('/settings')
async def settings():
    return store.public()


@router.get('/account-snapshot')
async def account_snapshot():
    """Lightweight read-only polling; never runs readiness or touches orders."""
    from datetime import datetime, timezone
    values=store.read()
    account,positions,orders,clock=await asyncio.gather(
        broker('/v2/account',values),broker('/v2/positions',values),
        broker('/v2/orders',values,params=dict(status='all',limit=50,direction='desc',nested='false')),
        broker('/v2/clock',values))
    if values.get('paper_account_id') and account.get('id')!=values['paper_account_id']:
        raise HTTPException(409,'The broker account no longer matches the saved connection. Review Settings.')
    def fields(record,names):return {name:record.get(name) for name in names}
    return dict(account_id=values.get('paper_account_id'),updated_at=datetime.now(timezone.utc).isoformat(),
                account=fields(account,('equity','cash','buying_power','last_equity','status')),
                positions=[fields(p,('symbol','qty','market_value','unrealized_pl','side')) for p in positions],
                orders=[fields(o,('id','symbol','side','type','qty','notional','filled_qty','filled_avg_price','status','submitted_at','filled_at','updated_at')) for o in orders],
                clock=fields(clock,('is_open','timestamp','next_open','next_close')))


@router.get('/equity-history')
async def equity_history(period: Literal['1D','1W','1M','3M','1Y']='1M'):
    """Broker account-equity history, normalized without exposing saved keys."""
    from datetime import datetime, timezone
    ranges={'1D':('1D','5Min'),'1W':('1W','1H'),'1M':('1M','1D'),'3M':('3M','1D'),'1Y':('1A','1D')}
    if period not in ranges:raise HTTPException(422,'Choose a supported equity-history period.')
    values=store.read();span,timeframe=ranges[period];now=datetime.now(timezone.utc)
    params=dict(period=span,timeframe=timeframe,end=now.isoformat())
    if timeframe!='1D':params.update(intraday_reporting='continuous',pnl_reset='no_reset')
    history=await broker('/v2/account/portfolio/history',values,params=params)
    timestamps=history.get('timestamp') or [];equities=history.get('equity') or []
    if len(timestamps)!=len(equities):
        raise HTTPException(502,'Broker equity history is incomplete. Try refreshing the chart.')
    points={}
    for stamp,value in zip(timestamps,equities):
        if isinstance(stamp,bool) or isinstance(value,bool) or stamp is None or value is None:continue
        try:stamp=float(stamp);equity=float(value)
        except (ValueError,TypeError,OverflowError):continue
        if not (math.isfinite(stamp) and math.isfinite(equity) and 0<stamp<=now.timestamp()):continue
        points[int(stamp)]=equity
    return dict(account_id=values.get('paper_account_id'),period=period,timeframe=timeframe,
                points=[dict(timestamp=stamp,equity=value) for stamp,value in sorted(points.items())],
                updated_at=now.isoformat(),source='Alpaca paper account')

@router.put('/settings')
async def save_settings(req: Settings):
    from backend.main import runtime
    async with control_lock:
        ai_only_update = bool(req.model_fields_set) and req.model_fields_set <= {'ai_enabled','ai_api_key','ai_model'}
        if any(runtime.alive(s) for s in runtime.processes) and not ai_only_update:
            raise HTTPException(409, 'Stop the engine before changing trading settings.')
        values = req.model_dump(exclude_unset=True, exclude_none=True)
        if req.api_key is not None: values['api_key'] = req.api_key.strip()
        if req.secret_key is not None: values['secret_key'] = req.secret_key.strip()
        if bool(req.api_key) != bool(req.secret_key):
            raise HTTPException(422, 'Supply both broker keys together, or leave both blank to keep saved keys.')
        from research.notifications import validate_webhook
        if req.slack_webhook is not None:
            try:values['slack_webhook'] = validate_webhook(req.slack_webhook.strip())
            except ValueError as error:raise HTTPException(422, str(error))
        previous = store.read()
        values = {**previous, **values}
        if req.ai_api_key is not None:
            values['ai_api_key']=req.ai_api_key.strip()
            if any(c.isspace() for c in values['ai_api_key']):raise HTTPException(422,'The AI API key must not contain whitespace.')
        if not values.get('ai_api_key'):values['ai_enabled']=False
        from research.models import model_info
        try:model_info(values['ai_model'])
        except ValueError as error:raise HTTPException(422,str(error))
        if not values.get('strategies') or len(values['strategies']) != len(set(values['strategies'])) or any(s not in IDS for s in values['strategies']):
            raise HTTPException(422, 'Select at least one supported strategy, without duplicates.')
        if any(s in SHORT_IDS for s in values['strategies']) and not values['shorts_enabled']:
            raise HTTPException(422, 'Enable shorts or untick the short strategies.')
        if 'news' in values['strategies'] and not values['news_enabled']:
            raise HTTPException(422, 'Enable news trading or untick News Catalyst Momentum.')
        if values.get('slack_notifications') and not values.get('slack_webhook'):
            raise HTTPException(422,'Add a Slack incoming webhook before enabling notifications.')
        if not values.get('close_on_stop'):
            raise HTTPException(422, 'For this paper release, closing positions on Stop must stay enabled.')
        if req.api_key:
            account = await broker('/v2/account', values)
            if account.get('status') != 'ACTIVE' or account.get('trading_blocked') or account.get('account_blocked'):
                raise HTTPException(409, 'The paper broker account is not active or is restricted.')
            if not account.get('id'):
                raise HTTPException(502, 'Broker account identity missing. Settings were not saved.')
            values['paper_account_id'] = account['id']
            if previous.get('paper_account_id') and previous['paper_account_id'] != account['id']:
                try:
                    equity = float(account['equity'])
                    if not math.isfinite(equity) or equity <= 0: raise ValueError()
                except (ValueError, KeyError, TypeError):
                    raise HTTPException(409, 'New paper account equity is invalid; connection was not saved.')
                # Keep the configured drawdown ratio when changing paper accounts.
                ratio = previous['halt_equity'] / previous['starting_capital']
                values['starting_capital'] = equity
                values['halt_equity'] = round(equity * ratio, 2)
        if values['halt_equity'] >= values['starting_capital']:
            raise HTTPException(422, 'Equity halt must be below reference capital.')
        store.write(values)
    return store.public()

@router.get('/readiness')
async def readiness():
    from backend.main import runtime
    values = store.read()
    checks = []
    def check(label, ok, detail, blocking=True):
        checks.append(dict(label=label, ok=bool(ok), detail=detail, blocking=blocking))
    check('Paper trading', True, 'All managed trading uses the paper broker. Live orders are disabled.')
    account, clock, positions, orders = {}, {}, [], []
    for label, path in [('Broker account','/v2/account'),('Market calendar','/v2/clock'),('Broker positions','/v2/positions'),('Pending orders','/v2/orders?status=open&limit=500')]:
        try:
            result = await broker(path, values)
            if label == 'Broker account':
                account = result
                ok = (result.get('status') == 'ACTIVE' and not result.get('trading_blocked') and not result.get('account_blocked') and not result.get('trade_suspended_by_user'))
                check(label, ok, 'Account active and unrestricted.' if ok else 'Account is restricted or inactive.')
            elif label == 'Market calendar':
                clock = result
                check(label, bool(result.get('timestamp') and result.get('next_open')), 'Market open.' if result.get('is_open') else 'Market closed. Next open: '+str(result.get('next_open','unknown')))
            elif label == 'Broker positions':
                positions = result
                check(label, True, f'{len(result)} existing broker positions. They count toward risk limits and are monitored without automatic liquidation.', blocking=False)
            else:
                orders = result
                check(label, True, f'{len(result)} pending broker orders. They are preserved; new entries on those symbols are blocked to prevent duplicates.', blocking=False)
        except HTTPException as e:
            check(label, False, str(e.detail))
    try:
        snapshot = await broker('/v2/stocks/snapshots', values, data=True, params={'symbols':'AAPL','feed':'iex'})
        from datetime import datetime, timedelta, timezone
        since = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%d')
        bars = await broker('/v2/stocks/bars', values, data=True, params={'symbols':'AAPL','timeframe':'1Day','start':since,'limit':5,'feed':'iex'})
        check('Market data', bool(snapshot.get('AAPL') and bars.get('bars',{}).get('AAPL')), 'IEX snapshot and historical bars checked; no order submitted.')
    except HTTPException as e:
        check('Market data', False, str(e.detail))
    try:
        equity = float(account.get('equity') or 0)
        buying_power = float(account.get('buying_power') or 0)
    except (ValueError, TypeError):
        equity, buying_power = 0, 0
    if any(s in SHORT_IDS for s in values['strategies']):
        check('Short selling permission', equity >= 2000 and account.get('shorting_enabled') is True,
              'Short strategies require broker shorting permission, at least $2,000 equity, and whole-share easy-to-borrow assets.')
    if 'news' in values['strategies']:
        try:
            result = await broker('/v1beta1/news', values, data=True, params={'symbols':'AAPL','limit':1})
            check('News feed', isinstance(result.get('news'), list), 'Alpaca news access checked. News trades require fresh catalysts and price/volume confirmation during the regular session.')
        except HTTPException as e:
            check('News feed', False, str(e.detail))
    if account.get('id') and values.get('paper_account_id'):
        check('Saved account identity', account['id'] == values['paper_account_id'], 'Verified keys must match the saved paper-account identity.')
    check('Equity and buying power', math.isfinite(equity) and math.isfinite(buying_power) and equity > values['halt_equity'] and buying_power > 0,
          'Equity must exceed the halt level, with positive buying power.')
    trade_budget=0
    try:
        if values['allocation_mode']=='fill_slots':
            from allocation import allocation_capacity,allocation_budget
            from strategy_catalog import NAMES
            budgets=[]
            for strategy in values['strategies']:
                try:
                    state=allocation_capacity(account,positions,orders,NAMES[strategy],values['max_positions'],values['max_gross_exposure_pct']/100,values['buying_power_reserve_pct'])
                    budgets.append(min(allocation_budget(state,values['max_order_value'])*values['position_size_multiplier'],state['capacity'],values['max_order_value']))
                except (ValueError,TypeError,KeyError):continue
            trade_budget=max(budgets,default=0)
        else:
            from allocation import allocation_capacity
            from strategy_catalog import NAMES
            budgets=[]
            for strategy in values['strategies']:
                state=allocation_capacity(account,positions,orders,NAMES[strategy],values['max_positions'],values['max_gross_exposure_pct']/100,values['buying_power_reserve_pct'])
                base=min(buying_power*values['max_position_pct']/100,values['max_order_value'],buying_power)
                budgets.append(min(base*values['position_size_multiplier'],state['capacity'],values['max_order_value']) if state['slots'] else 0)
            trade_budget=max(budgets,default=0)
    except (ValueError,TypeError,KeyError):pass
    # A full account may still start to manage exits; capacity blocks entries only.
    check('New-entry allocation', True, f'Current maximum new-entry budget: ${trade_budget:.2f}. No capacity or no free slots prevents entries, while position management can continue.',blocking=False)
    import hashlib
    from datetime import datetime
    import zoneinfo
    identity = values.get('paper_account_id') or values.get('api_key', '')
    risk_id = hashlib.sha256(('paper:' + identity).encode()).hexdigest()[:24]
    risk_path = store.directory / ('risk-' + risk_id + '.json')
    risk_ok = True
    risk_detail = 'No persisted risk halt.'
    if risk_path.exists():
        try:
            import json
            state = json.loads(risk_path.read_text())
            today = datetime.now(zoneinfo.ZoneInfo('America/New_York')).strftime('%Y-%m-%d')
            baseline = float(state['baseline'])
            risk_ok = math.isfinite(baseline) and baseline > 0 and not state['bot_halted']
            if state['day'] == today:
                risk_ok = risk_ok and not state['daily_halted'] and equity > baseline * (1-values['max_daily_loss_pct']/100)
            risk_detail = 'Persisted risk limits checked.' if risk_ok else 'A persisted risk halt or daily loss limit blocks new entries. Review the risk checkpoint before restarting.'
        except Exception:
            risk_ok, risk_detail = False, 'Risk checkpoint invalid; review it before restarting.'
    check('Persisted risk limits', risk_ok, risk_detail)
    from research.config import ResearchConfig
    import os
    policy=ResearchConfig.from_env(settings=values)
    if policy.enabled:
        check('AI provider configuration', bool(values.get('ai_api_key')), 'AI-dependent entries require a configured provider key; missing credentials block new entries.')
        if policy.prototype:
            check('Prototype company research', True, 'One preliminary AI comparison of the complete technical pool, then up to three companies with two web searches each, seven-day cache and the existing $0.20/day estimated budget. Missing or unverified evidence blocks swing entries; scalping is independent of AI.', blocking=False)
        elif policy.require_fundamentals or policy.require_earnings:
            evidence=os.getenv('AI_EVIDENCE_FILE','')
            check('Research evidence feed', bool(evidence and Path(evidence).is_file()), 'A dated fundamentals/earnings evidence feed must be available to the worker.')
    return dict(ready=all(x['ok'] for x in checks if x['blocking']), checks=checks, paper=True,
                account={k:account.get(k) for k in ('equity','cash','buying_power','status','daytrade_count')},
                clock=clock, positions=positions, orders=orders,
                recovery='Existing holdings and pending orders do not prevent startup. Existing holdings remain broker-managed; new engine trades retain their deterministic exits. Automatic engine restart is disabled.')

@router.post('/start')
async def start():
    from backend.main import bot_start, BotStartRequest, runtime
    async with control_lock:
        if any(runtime.alive(s) for s in runtime.processes):
            raise HTTPException(409, 'The engine is already running.')
        status = await readiness()
        if not status['ready']:
            raise HTTPException(409, 'Readiness checks failed. Open the Readiness panel for details.')
        values = store.read()
        return await bot_start(BotStartRequest(api_key=values['api_key'], secret_key=values['secret_key'], paper=True, strategy=values['strategy']))

@router.post('/stop')
async def stop():
    from backend.main import bot_stop
    async with control_lock:
        return await bot_stop()

@router.get('/status')
async def status():
    from backend.main import bot_status, _read_bot_state
    result = await bot_status()
    result['state'] = _read_bot_state() if result['running'] else {}
    result['paper'] = True
    result['enabled_strategies'] = store.read()['strategies']
    return result

@router.get('/strategies')
async def strategy_catalog():
    return CATALOG


@router.get('/research')
async def research_status():
    from research.config import ResearchConfig
    from research.db import ResearchDB
    from research.gate import db_path
    from research.calendar import ET
    from datetime import datetime
    values=store.read();config=ResearchConfig.from_env(settings=values);db=ResearchDB(db_path())
    day=datetime.now(ET).date().isoformat();identity=store.read().get('paper_account_id','unconfigured')
    from research.diagnostics import research_diagnostics, empty_summary
    diagnostics=research_diagnostics(db,identity,config.model,day)
    reports=[r for r in db.recent('daily_report',20) if r['key'].startswith(identity+':')][:4]
    for report in reports:
        if (report['key']==identity+':'+day+':premarket'
                and report['payload'].get('summary')=='No qualifying candidates or reviewable holdings; no AI ranking call was made.'
                and diagnostics['company_results']):
            report['payload']={**report['payload'],'summary':empty_summary(diagnostics)}
    return dict(enabled=config.enabled,provider=config.provider,model=config.model,
                credentials_configured=bool(values.get('ai_api_key')),
                prototype=config.prototype,batch_review=config.batch_review,daily_budget=config.dollars,max_candidates=config.candidates,
                max_searches=6 if config.prototype else 0,cache_days=config.company_cache_days,
                evidence_configured=bool(__import__('os').getenv('AI_EVIDENCE_FILE') and Path(__import__('os').getenv('AI_EVIDENCE_FILE')).is_file()),
                usage=db.usage(day),watchlist=db.get('watchlist',identity+':'+day) or {},
                reports=reports,diagnostics=diagnostics,heartbeat=db.get('worker','heartbeat'),schedule=local_schedule(db,config))

@router.post('/notifications/test')
async def notification_test():
    from research.notifications import enqueue
    from research.db import ResearchDB
    from research.gate import db_path
    import uuid
    settings=store.read()
    if not settings.get('slack_notifications') or not settings.get('slack_webhook'):
        raise HTTPException(409, 'Save and enable your Slack webhook first.')
    enqueue(ResearchDB(db_path()),uuid.uuid4().hex,'Notification test',{'message':'Your paper trade notifications are connected.'})
    return {'status':'queued','detail':'The research/notification worker will deliver this test.'}


@router.get('/ai-models')
async def ai_models():
    from research.models import model_choices
    return model_choices()

def local_schedule(db,config):
    from research.calendar import ExchangeCalendar,ET
    from datetime import datetime
    from zoneinfo import ZoneInfo
    now=datetime.now(ET);day=now.date().isoformat()
    rows=db.get('calendar',day)
    if rows is None:return {'timezone':'Europe/Malta','status':'Waiting for exchange calendar'}
    session=ExchangeCalendar(lambda start,end:rows).session(day)
    if session is None:return {'timezone':'Europe/Malta','status':'No trading session today'}
    schedule=session.schedule(config)
    return dict(timezone='Europe/Malta',date=day,status='Exchange calendar loaded',
                premarket=schedule['premarket'].astimezone(ZoneInfo('Europe/Malta')).isoformat(),
                market_open=session.opening.astimezone(ZoneInfo('Europe/Malta')).isoformat(),
                entry_validation=schedule['entry'].astimezone(ZoneInfo('Europe/Malta')).isoformat(),
                postmarket=schedule['postmarket'].astimezone(ZoneInfo('Europe/Malta')).isoformat())

@router.get('/daily-summary')
async def daily_summary():
    from daily_summary import closing_report
    try:
        return await closing_report(broker,store.read(),store.directory/'summaries')
    except (ValueError,KeyError,TypeError):
        raise HTTPException(502,'Broker summary data is incomplete or belongs to another account. Retry shortly.')
