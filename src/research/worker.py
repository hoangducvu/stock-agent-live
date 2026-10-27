"""Independent research/notification process. Never imports or submits broker orders."""
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import signal
import time
from backend.settings_store import SettingsStore
from .calendar import ExchangeCalendar, ET
from .config import ResearchConfig
from .data import AlpacaResearchData, EvidenceFile, summarize_bars, screen
from .db import ResearchDB
from .gate import db_path, deterministic_entry
from .provider import build_provider
from .service import AIService, fingerprint
from .notifications import deliver

SCAN_BATCH_SIZE = 100
UNIVERSE_POLICY = 'all_active_tradable_us_equities'

class ResearchWorker:
    def __init__(self,db,config,data,evidence,provider,scope):
        self.db=db;self.config=config;self.data=data;self.evidence=evidence;self.scope=scope
        self.calendar=ExchangeCalendar(data.calendar,db);self.ai=AIService(db,config,provider)
        if config.prototype:
            from .company import CachedEvidence,CompanyResearch
            self.evidence=CachedEvidence(db,scope,config.model,evidence)
            self.company=CompanyResearch(db,config,provider,self.evidence)
    def intraday_symbols(self):
        from scalp_exits import INTRADAY
        try:
            state=json.loads((Path(__file__).resolve().parents[1]/'data'/'bot_state.json').read_text())
            return {p['symbol'] for p in state.get('positions',[]) if p.get('strategy') in INTRADAY}
        except (OSError,ValueError,KeyError):return set()
    def portfolio(self,now):
        portfolio=self.data.portfolio();portfolio['sectors']={}
        for p in portfolio['positions']:
            evidence=self.evidence.get(p['symbol'],now)
            if evidence:portfolio['sectors'][p['symbol']]=evidence.get('sector')
        open_orders=self.data.get('/v2/orders',dict(status='open',limit=500))
        portfolio['pending_orders']=open_orders
        for order in open_orders:
            symbol=order.get('symbol')
            if symbol and symbol not in portfolio['sectors']:
                evidence=self.evidence.get(symbol,now)
                if evidence:portfolio['sectors'][symbol]=evidence.get('sector')
        self.db.reconcile_positions(self.scope,{p['symbol'] for p in portfolio['positions']},{o['symbol'] for o in open_orders})
        self.db.put('portfolio',self.scope,portfolio)
        self.db.put('portfolio_snapshot',self.scope+':'+now.isoformat(),portfolio)
        return portfolio

    def scan_summaries(self,universe,through,expected,benchmark_return,held_symbols,task,key,base_bars):
        """Summarize every symbol in bounded batches before ranking or paid AI.

        Keep only compact summaries and rejection reasons. Raw daily history for
        the whole market would otherwise consume memory alongside the live bot.
        A failed batch prevents a partial-universe shortlist from reaching AI.
        """
        summaries=[];unavailable=[];held=[]
        progress=dict(status='scanning',phase=task,policy=UNIVERSE_POLICY,
                      total=len(universe),processed=0,available=0,data_rejected=0,
                      held_excluded=0,feed='iex',batch_size=SCAN_BATCH_SIZE)
        def publish():
            progress['updated_at']=datetime.now(timezone.utc).isoformat()
            self.db.put('scan_progress',key,dict(progress))
        publish()
        try:
            for offset in range(0,len(universe),SCAN_BATCH_SIZE):
                batch=universe[offset:offset+SCAN_BATCH_SIZE]
                missing=[s for s in batch if s not in base_bars]
                batch_bars=self.data.daily(missing,through) if missing else {}
                for symbol in batch:
                    history=base_bars.get(symbol,batch_bars.get(symbol,[]))
                    try:
                        row=summarize_bars(symbol,history,benchmark_return)
                        if row is None:
                            code='daily_history_unavailable'
                            message=f'No usable daily summary: at least 201 distinct daily bars and finite indicators are required ({len(history)} bars returned).'
                        else:
                            actual=datetime.fromisoformat(row['data_timestamp'].replace('Z','+00:00')).astimezone(ET).date().isoformat()
                            if actual!=expected:
                                code='stale_daily_data'
                                message=f'Latest daily session {actual} does not match the required completed session {expected}.'
                            elif task=='premarket' and self.config.prototype and symbol in held_symbols:
                                held.append(dict(ticker=symbol,reasons=['already_held'],reason_details=[dict(code='already_held',message='Already held; excluded from new-entry research and eligible for the separate holdings review.')]))
                                continue
                            else:
                                summaries.append(row)
                                continue
                    except (ValueError,TypeError,KeyError,IndexError,ZeroDivisionError,OverflowError):
                        code='invalid_daily_data'
                        message='Daily bars contain missing, invalid, or non-finite price/volume/timestamp values.'
                    unavailable.append(dict(ticker=symbol,reasons=[code],reason_details=[dict(code=code,message=message)]))
                progress.update(processed=offset+len(batch),available=len(summaries)+len(held),
                                data_rejected=len(unavailable),held_excluded=len(held))
                publish()
                # Drop history before fetching the next batch, including the
                # loop's reference to its final symbol's raw history.
                batch_bars={};history=[]
        except Exception as error:
            progress.update(status='failed',reason='market_data_scan_failed',exception_type=type(error).__name__)
            publish()
            raise RuntimeError('Full-universe market-data scan failed; no AI shortlist was submitted') from None
        progress['status']='complete'
        publish()
        return summaries,unavailable,held

    def research(self,task,now,session):
        day=session.day;key=self.scope+':'+day
        if task=='premarket':self.db.put('watchlist',key,{},session.closing.timestamp())
        universe=[] if self.config.prototype and task=='postmarket' else list(dict.fromkeys(self.data.universe()))
        # A holdings-only postmarket review must not erase premarket coverage.
        if not (self.config.prototype and task=='postmarket'):
            self.db.put('universe',key,universe)
            self.db.put('universe_selection',key,dict(policy=UNIVERSE_POLICY,total=len(universe),alphabetical_cutoff=False))
        # Premarket uses only fully completed prior-session candles.
        through=now.astimezone(ET)
        if task=='premarket':through=through-timedelta(days=1)
        held_symbols=[p['symbol'] for p in self.portfolio(now)['positions']]
        # Retain only benchmark/sector/holding histories. Universe histories are
        # fetched and released batch by batch below.
        symbols=list(dict.fromkeys(['SPY','QQQ','XLK','XLF','XLV','XLE','XLI','XLP','XLY','XLU','XLB','XLRE','XLC']+held_symbols))
        bars=self.data.daily(symbols,through)
        sessions=self.data.calendar((through-timedelta(days=10)).date().isoformat(),through.date().isoformat())
        expected=max((r['date'] for r in sessions),default=None)
        if expected is None:raise RuntimeError('Expected completed exchange session unavailable')
        def completed(row):
            return row and datetime.fromisoformat(row['data_timestamp'].replace('Z','+00:00')).astimezone(ET).date().isoformat()==expected
        benchmark=summarize_bars('SPY',bars.get('SPY',[]))
        if not completed(benchmark):raise RuntimeError('Benchmark daily data unavailable or stale')
        if task=='postmarket':
            stamp=datetime.fromisoformat(benchmark['data_timestamp'].replace('Z','+00:00'))
            if stamp.astimezone(ET).date()!=session.opening.date():raise RuntimeError('Completed session daily bar not available')
        summaries=[];data_rejections=[];held_exclusions=[]
        if universe:
            summaries,data_rejections,held_exclusions=self.scan_summaries(
                universe,through,expected,benchmark['return_20d'],set(held_symbols),task,key,bars)
        screening_policy=self.config
        screening_evidence=self.evidence
        if self.config.prototype:
            from dataclasses import replace
            from types import SimpleNamespace
            screening_policy=replace(self.config,require_fundamentals=False,require_earnings=False)
            screening_evidence=SimpleNamespace(get=lambda *_:None)
        candidates,rejections=screen(summaries,screening_evidence,screening_policy,now)
        technical=dict(screened=len(universe),available=len(summaries),
                       candidates=candidates,rejections=rejections,expected_session=expected,
                       data_rejections=data_rejections,held_exclusions=held_exclusions,
                       qualified=len(candidates)+sum(r['reasons']==['shortlist_limit'] for r in rejections),
                       shortlist_limit=self.config.candidates,policy=UNIVERSE_POLICY)
        self.db.put('technical_screening',key+':'+task,technical)
        if task=='premarket':self.db.put('technical_screening',key,technical)
        self.db.put('screening',key,dict(screened=len(universe),available=len(summaries),candidates=candidates,rejections=rejections))
        for row in candidates:
            row['regime']='uptrend' if benchmark['price']>benchmark['sma200'] else 'risk_off'
            row['snapshot_version']=fingerprint(row)
            self.db.put('screened',self.scope+':'+row['ticker'],row,now.timestamp()+86400)
        portfolio=self.portfolio(now)
        context=dict(scope=self.scope,trading_date=day,benchmark=benchmark,
                     sectors={s:summarize_bars(s,bars.get(s,[]),benchmark['return_20d']) for s in symbols[1:13]},
                     portfolio=dict(equity=portfolio['account']['equity'],cash=portfolio['account']['cash'],buying_power=portfolio['account']['buying_power'],
                                    positions=[{k:p.get(k) for k in ('symbol','market_value','unrealized_pl','side')} for p in portfolio['positions']]))
        if self.config.prototype:
            context['benchmark']={k:benchmark.get(k) for k in ('ticker','price','sma50','sma200','return_1d','return_20d','data_timestamp')}
            context['sectors']={symbol:({k:row.get(k) for k in ('return_1d','return_20d','relative_strength')} if row else None) for symbol,row in context['sectors'].items()}
        if task=='postmarket':
            # Holdings are reviewed even if they no longer pass entry screening.
            held=[]
            for p in portfolio['positions']:
                if self.config.prototype and p['symbol'] in self.intraday_symbols():continue
                symbol=p['symbol'];summary=summarize_bars(symbol,bars.get(symbol,[]),benchmark['return_20d'])
                if summary:held.append(summary)
            candidates=list({r['ticker']:r for r in held+candidates}.values())[:self.config.candidates]
        try:news=self.data.news([r['ticker'] for r in candidates]) if candidates else [];news_available=True
        except Exception:news=[];context['missing_news']=True;news_available=False
        try:
            market_news=self.data.news(['SPY','QQQ'])[:5]
            context['overnight_market_news']=[dict(headline=n.get('headline','')[:180],created_at=n.get('created_at'),source=n.get('url','')) for n in market_news]
        except Exception:market_news=[];context['missing_market_news']=True
        if self.config.prototype:
            for row in candidates:
                articles=[a for a in news if row['ticker'] in a.get('symbols',[])]
                record=self.company.refresh(row['ticker'],row['price'],articles,now,news_available)
                outcome=self.db.get('company_result',self.evidence.key(row['ticker'])+':'+day)
                if outcome:row['research_outcome']=outcome
                if record:
                    row.update(sector=record.get('sector'),fundamentals=record.get('fundamentals'),next_earnings=record.get('next_earnings'),
                               company_summary=record.get('summary'),company_risks=record.get('risks'),research_observed_at=record['observed_at'],research_anchor_price=record.get('anchor_price'))
                    row['source_references']+=record['source_references']
                row['missing_required_evidence']=[]
                if not row.get('fundamentals'):row['missing_required_evidence'].append('fundamentals')
                if not row.get('next_earnings'):row['missing_required_evidence'].append('earnings')
                if not news_available:row['missing_required_evidence'].append('news_freshness')
            if task=='premarket':
                # Reapply strict earnings/evidence checks after bounded web research.
                candidates,rejections=screen(candidates,self.evidence,self.config,now)
                for rejection in rejections:
                    outcome=self.db.get('company_result',self.evidence.key(rejection['ticker'])+':'+day)
                    if outcome:rejection['research_outcome']=outcome
                if not news_available:candidates=[]
                self.db.put('screening',key,dict(screened=len(universe),available=len(summaries),candidates=candidates,rejections=rejections))
        for row in candidates:
            try:
                snapshot=self.data.snapshot(row['ticker'])
                trade=snapshot.get('latestTrade',{});minute=snapshot.get('minuteBar',{})
                trade_time=datetime.fromisoformat(trade.get('t','').replace('Z','+00:00'))
                if trade_time.astimezone(ET).date()==now.astimezone(ET).date() and 0<=(now-trade_time).total_seconds()<=900:
                    row['premarket']={'price':trade.get('p'),'timestamp':trade['t'],'minute_volume':minute.get('v')}
                else:row['premarket']=None
            except Exception:row['premarket']=None
            row['source_references']+=[n['url'] for n in market_news if n.get('url')]
            articles=[n for n in news if row['ticker'] in n.get('symbols',[])][:3]
            row['news']=[dict(headline=n.get('headline','')[:180],created_at=n.get('created_at'),source=n.get('url','')) for n in articles]
            row['source_references']+= [n['url'] for n in articles if n.get('url')]
            row['snapshot_version']=fingerprint(row)
            if task=='premarket':self.db.put('screened',self.scope+':'+row['ticker'],row,session.closing.timestamp())
        # Every context is persisted; no historical responses are manufactured.
        self.db.put('research_input',key+':'+task,dict(candidates=candidates,context=context))
        if task=='premarket':
            self.db.put('premarket_screening',key,self.db.get('screening',key))
        if not candidates:
            if task=='premarket':self.db.put('watchlist',key,{},session.closing.timestamp())
            self.db.event('empty_research',key,dict(task=task,reasons='No evidence-complete candidates'))
            from .diagnostics import research_diagnostics, empty_summary
            diagnostic=research_diagnostics(self.db,self.scope,self.config.model,day)
            summary=(empty_summary(diagnostic) if task=='premarket' else
                     'No evidence-complete candidates or reviewable holdings were available for the postmarket review; final AI ranking was skipped.')
            self.db.put('daily_report',key+':'+task,dict(recommendations=[],summary=summary,
                        status='research_failed' if task=='premarket' and any(r['status'] in {'rejected','provider_failed'} for r in diagnostic['company_results']) else 'no_candidates'))
            self.db.put('daily_summary',key,dict(screened=len(universe),candidates=0,watchlist=0,usage=self.db.usage(day)))
            return True
        # Bound the batch to configured token ceiling; persist omitted candidates.
        report=None
        while candidates:
            snapshots={r['ticker']:r for r in candidates}
            # One practical batch. If it exceeds the input ceiling, shrink locally
            # without making additional provider requests.
            from .service import SYSTEM, canonical
            from .schemas import Report
            overhead=len((SYSTEM+'\nJSON schema: '+canonical(Report.model_json_schema())).encode())+512
            size=len(canonical(dict(context={**context,'task':task,'model_name':self.config.model,'analysis_timestamp':now.isoformat()},snapshots=snapshots)).encode())
            if overhead+size+min(2000 if self.config.prototype else 4000,self.config.tokens//3)<=self.config.tokens:
                report=self.ai.evaluate(task,snapshots,context,now);break
            candidates.pop()
        if report is None:return False
        if task=='premarket':
            approved={r.ticker:snapshots[r.ticker] for r in report.recommendations if r.action=='BUY'}
            self.db.put('watchlist',key,approved,session.closing.timestamp())
        self.db.put('daily_report',key+':'+task,report.model_dump(mode='json'))
        self.db.put('daily_summary',key,dict(screened=len(universe),candidates=len(candidates),watchlist=len(self.db.get('watchlist',key) or {}),usage=self.db.usage(day)))
        return True
    def prepare_watchlist(self,now,session):
        watch=self.db.get('watchlist',self.scope+':'+session.day) or {}
        missing=[s for s in watch if self.db.get('watch_bars',self.scope+':'+session.day+':'+s) is None]
        if not missing:return
        intraday=self.data.intraday(missing)
        daily=self.data.daily(missing,now.astimezone(ET)-timedelta(days=1))
        for symbol in missing:
            if len(intraday.get(symbol,[]))<55 or len(daily.get(symbol,[]))<201:continue
            self.db.put('watch_bars',self.scope+':'+session.day+':'+symbol,dict(daily=daily[symbol],intraday=intraday[symbol]),session.closing.timestamp())

    def entries(self,now,session):
        pending=self.db.pending(session.day)
        # Recheck approved setups continuously without AI so the trading loop can
        # consume fresh quotes/exposure at its next five-minute tick.
        refresh=self.db.recent('active_entry',30)
        signals=pending+[r['payload'] for r in refresh if r['payload'].get('day')==session.day]
        seen=set();evaluations=[]
        for signal_row in signals:
            key=signal_row.get('key');payload=signal_row['payload']
            if key in seen or payload.get('scope')!=self.scope:continue
            from scalp_exits import INTRADAY
            if self.config.prototype and payload.get('strategy') in INTRADAY:
                self.db.signal_status(key,'superseded');self.db.delete('active_entry',key);continue
            if payload.get('model',self.config.model)!=self.config.model:
                self.db.signal_status(key,'superseded');self.db.delete('active_entry',key);continue
            seen.add(key)
            timestamp=datetime.fromisoformat(payload['signal_timestamp'])
            if (now-timestamp).total_seconds()>self.config.cooldown_minutes*60:
                self.db.signal_status(key,'expired');self.db.delete('active_entry',key);continue
            watch=payload['watch'];symbol=payload['ticker']
            try:
                material_key=self.scope+':'+symbol
                material=self.db.get('material',material_key)
                if material is None:
                    evidence=self.evidence.get(symbol,now)
                    articles=self.data.news([symbol])[:3]
                    if self.config.prototype:
                        from .company import MATERIAL_WORDS,material_digest
                        cached=self.db.get('company_research',self.evidence.key(symbol),now.timestamp())
                        signatures={material_digest([a]) for a in articles if any(w in a.get('headline','').lower() for w in MATERIAL_WORDS)}
                        if cached and signatures-set(cached.get('news_fingerprints',[])):
                            self.db.delete('company_research',self.evidence.key(symbol))
                            evidence=None
                    digest=fingerprint(dict(news=[(a.get('id'),a.get('updated_at'),a.get('headline')) for a in articles],evidence=evidence))
                    material=dict(digest=digest,evidence=evidence,articles=articles)
                    self.db.put('material',material_key,material,now.timestamp()+300)
                if material['digest']!=watch.get('material_digest'):
                    watch=dict(watch);watch['material_digest']=material['digest']
                    evidence=material['evidence'] or {}
                    watch.update(sector=evidence.get('sector'),fundamentals=evidence.get('fundamentals'),next_earnings=evidence.get('next_earnings'))
                    watch['news']=[dict(headline=a.get('headline','')[:180],created_at=a.get('created_at'),source=a.get('url','')) for a in material['articles']]
                    watch['source_references']=list(dict.fromkeys(watch.get('source_references',[])+[a['url'] for a in material['articles'] if a.get('url')]+evidence.get('source_references',[])))
                    watch['snapshot_version']=fingerprint({k:v for k,v in watch.items() if k!='snapshot_version'})
                    daykey=self.scope+':'+session.day
                    current=self.db.get('watchlist',daykey) or {}
                    if symbol in current:
                        current[symbol]=watch;self.db.put('watchlist',daykey,current,session.closing.timestamp())
                    self.db.put('screened',self.scope+':'+symbol,watch,session.closing.timestamp())
                    self.db.put('entry_decision',key,dict(action='REVIEW'),now.timestamp()+self.config.cooldown_minutes*60)
                    self.db.put('entry_check',key,dict(allowed=False,reasons=['material_evidence_changed']),now.timestamp()+45)
                    self.db.signal_status(key,'superseded')
                    self.db.delete('active_entry',key)
                    continue
                snapshot=self.data.snapshot(symbol);asset=self.data.get('/v2/assets/'+symbol)
                snapshot['trading_status']='active' if asset.get('tradable') and asset.get('status')=='active' else 'blocked'
                portfolio=self.portfolio(now)
                check=deterministic_entry(snapshot,portfolio,{**watch,'strategy':payload['strategy']},self.config,payload['price']*payload['qty']*1.01,now)
                self.db.put('entry_check',key,check,now.timestamp()+45)
                if not check['allowed']:
                    self.db.event('risk_rejection',key,check);continue
                if not self.config.validation:
                    self.db.put('entry_decision',key,dict(action='BUY'),now.timestamp()+self.config.cooldown_minutes*60)
                elif not self.db.get('entry_decision',key):
                    fresh={**watch,'price':check['price'],'data_timestamp':snapshot['latestQuote']['t'],
                           'setup':{k:payload[k] for k in ('strategy','price','qty','signal_timestamp')}}
                    if not self.db.get('entry_attempt',key):evaluations.append(dict(key=key,symbol=symbol,fresh=fresh))
                    continue
                self.db.signal_status(key,'evaluated')
                self.db.put('active_entry',key,dict(key=key,day=session.day,payload=payload),now.timestamp()+self.config.cooldown_minutes*60)
            except Exception as error:self.db.event('entry_worker_error',key,dict(type=type(error).__name__))
        # Batch distinct tickers, preserving per-setup cooldown even when quote
        # timestamps advance. No repeated unchanged requests after an outage.
        unique={}
        for item in evaluations:unique.setdefault(item['symbol'],item)
        batch=list(unique.values())[:self.config.candidates]
        if batch:
            from .service import SYSTEM,canonical
            from .schemas import Report
            context=dict(scope=self.scope,trading_date=session.day)
            overhead=len((SYSTEM+'\nJSON schema: '+canonical(Report.model_json_schema())).encode())+512
            while batch:
                snapshots={item['symbol']:item['fresh'] for item in batch}
                total=overhead+len(canonical(dict(context={**context,'task':'entry','model_name':self.config.model,'analysis_timestamp':now.isoformat()},snapshots=snapshots)).encode())+min(2000 if self.config.prototype else 4000,self.config.tokens//3)
                if total<=self.config.tokens:break
                batch.pop()
            if batch:
                for item in batch:self.db.put('entry_attempt',item['key'],True,now.timestamp()+self.config.cooldown_minutes*60)
                report=self.ai.evaluate('entry',snapshots,context,now)
                if report is not None:
                    actions={r.ticker:r.action for r in report.recommendations}
                    for item in batch:
                        self.db.put('entry_decision',item['key'],dict(action=actions.get(item['symbol'],'REVIEW')),now.timestamp()+self.config.cooldown_minutes*60)
    def tick(self,now):
        session=self.calendar.session(now.astimezone(ET).date())
        if session is None:return
        key=self.scope+':'+session.day;schedule=session.schedule(self.config)
        self.db.put('session',key,dict(entry=schedule['entry'].isoformat(),close=session.closing.isoformat()),session.closing.timestamp()+86400)
        for phase,enabled in [('premarket',self.config.premarket),('postmarket',self.config.postmarket)]:
            due=schedule[phase]
            # Recovery: catch up research before session close; postmarket retry
            # until the day's completed candles arrive. Never replay old sessions.
            if not enabled or now<due or (phase=='premarket' and now>=session.closing):continue
            job=key+':'+phase
            if self.db.get('daily_report',job):
                self.db.finish(job,True,{'recovered_report':True});continue
            if self.db.claim(job,lease_seconds=1800,max_attempts=None):
                self.db.event('job_start',job,{})
                try:success=self.research(phase,now,session)
                except Exception as error:
                    success=False;self.db.event('job_error',job,dict(type=type(error).__name__))
                self.db.finish(job,success,{});self.db.event('job_complete',job,dict(success=success))
        if now<session.closing:
            try:self.prepare_watchlist(now,session)
            except Exception as error:self.db.event('watch_data_error',key,dict(type=type(error).__name__))
        if schedule['entry']<=now<session.closing:self.entries(now,session)

def run():
    stopped=False
    def stop(*_):
        nonlocal stopped;stopped=True
    signal.signal(signal.SIGTERM,stop);signal.signal(signal.SIGINT,stop)
    from bot_runtime import InstanceLock
    instance=InstanceLock(Path(db_path()).with_suffix('.worker.lock'))
    db=ResearchDB(db_path());store=SettingsStore(Path(__file__).resolve().parents[1]/'data')
    while not stopped:
        try:
            settings=store.read();deliver(db,settings);config=ResearchConfig.from_env(settings=settings)
            db.put('worker','heartbeat',dict(timestamp=datetime.now(timezone.utc).isoformat(),ai_enabled=config.enabled))
            if config.enabled:
                if not settings.get('api_key') or not settings.get('ai_api_key'):raise RuntimeError('Research credentials missing')
                scope=settings.get('paper_account_id','unconfigured')
                worker=ResearchWorker(db,config,AlpacaResearchData(settings),EvidenceFile(),build_provider(config,api_key=settings['ai_api_key'],managed=True),scope)
                worker.tick(datetime.now(timezone.utc))
        except Exception as error:db.event('worker_error','worker',dict(type=type(error).__name__))
        for _ in range(15):
            if stopped:break
            time.sleep(1)
if __name__=='__main__':run()
