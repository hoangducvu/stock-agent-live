"""Research safety tests. External model, broker and Slack calls are mocked."""
from datetime import datetime, timedelta, timezone
from dataclasses import replace
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'));sys.path.insert(0,'/app')
from research.config import ResearchConfig
from research.db import ResearchDB
from research.calendar import ExchangeCalendar, ET
from research.data import EvidenceFile, screen
from research.notifications import validate_webhook

class ResearchCoreTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=ResearchDB(Path(self.temp.name,'test.sqlite3'))
    def test_concurrent_budget_reservations_cannot_overspend(self):
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=8) as pool:
            results=list(pool.map(lambda _:self.db.reserve('day',.125,100,.5),range(16)))
        self.assertEqual(sum(bool(r) for r in results),4)
        self.assertEqual(self.db.usage('day')['cost'],.5)

    def test_atomic_budgets_and_uncertain_charges_survive_restart(self):
        reservation=self.db.reserve('2026-10-25',.05,2,.10);self.assertTrue(reservation)
        reopened=ResearchDB(self.db.path)
        self.assertTrue(reopened.reserve('2026-10-25',.05,2,.10))
        self.assertIsNone(reopened.reserve('2026-10-25',.01,2,1))
        self.assertAlmostEqual(reopened.usage('2026-10-25')['cost'],.10)
        self.assertTrue(reopened.reserve('2026-10-26',.01,2,1))
    def test_actual_usage_replaces_reservation(self):
        key=self.db.reserve('day',.1,20,1);self.db.settle(key,.02,100,50,'received')
        self.assertEqual(self.db.usage('day')['cost'],.02)
        self.assertEqual(self.db.usage('day')['input_tokens'],100)
    def test_jobs_recover_expired_lease_without_duplicate_completion(self):
        self.assertTrue(self.db.claim('research',lease_seconds=10,now=100))
        self.assertFalse(self.db.claim('research',lease_seconds=10,now=105))
        self.assertTrue(self.db.claim('research',lease_seconds=10,now=111))
        self.db.finish('research',True,{})
        self.assertFalse(self.db.claim('research',now=9999999999))
    def test_atomic_reservations_enforce_sector_exposure_between_broker_refreshes(self):
        checks=dict(portfolio_room=6000,sector_room=3000,broker_symbols=[])
        first=dict(scope='account',ticker='AAPL',sector='Technology',reserved_notional=2000)
        second={**first,'ticker':'MSFT'}
        self.assertTrue(self.db.reserve_entry('first',first,checks))
        self.assertFalse(self.db.reserve_entry('second',second,checks))
        self.db.order_result('first','filled',payload={'filled':True})
        self.assertFalse(self.db.reserve_entry('second',second,checks))
        self.db.reconcile_positions('account',{'AAPL'},set())
        self.db.reconcile_positions('account',set(),set())
        self.assertTrue(self.db.reserve_entry('second',second,checks))

    def test_order_intents_are_persistent_and_idempotent(self):
        self.assertTrue(self.db.order_intent('setup',{'ticker':'AAPL'}))
        self.assertFalse(ResearchDB(self.db.path).order_intent('setup',{'ticker':'AAPL'}))
    def test_calendar_holidays_and_early_close(self):
        fetch=Mock(side_effect=lambda start,end:[] if start=='2026-12-25' else [{'date':start,'open':'09:30','close':'13:00'}])
        calendar=ExchangeCalendar(fetch,self.db)
        self.assertIsNone(calendar.session('2026-12-25'))
        session=calendar.session('2026-11-27');schedule=session.schedule(ResearchConfig())
        self.assertEqual(schedule['postmarket'].hour,13);self.assertEqual(schedule['postmarket'].minute,15)
        self.assertEqual(schedule['entry'].hour,10)
        calendar.session('2026-11-27');self.assertEqual(fetch.call_count,2)
    def test_calendar_dst_uses_exchange_timezone(self):
        cal=ExchangeCalendar(lambda start,end:[{'date':start,'open':'09:30','close':'16:00'}])
        winter=cal.session('2026-01-05');summer=cal.session('2026-07-06')
        self.assertEqual(winter.opening.astimezone(timezone.utc).hour,14)
        self.assertEqual(summer.opening.astimezone(timezone.utc).hour,13)
    def test_calendar_outage_does_not_guess_weekday(self):
        cal=ExchangeCalendar(Mock(side_effect=OSError()))
        with self.assertRaises(OSError):cal.session('2026-10-26')
    def test_cache_expiration_and_signal_deduplication(self):
        self.db.put('cache','key',{'x':1},expires=200,now=100)
        self.assertIsNotNone(self.db.get('cache','key',now=150));self.assertIsNone(self.db.get('cache','key',now=201))
        self.assertTrue(self.db.queue_signal('signal','day','AAPL','rsi',{}))
        self.assertFalse(self.db.queue_signal('signal','day','AAPL','rsi',{}))
    def test_evidence_rejects_future_or_missing_sources(self):
        now=datetime(2026,10,25,tzinfo=timezone.utc);path=Path(self.temp.name,'evidence.json')
        path.write_text(json.dumps({'AAPL':dict(observed_at='2026-10-26T00:00:00Z',as_of='2026-10-20T00:00:00Z',source_references=['filing'])}))
        self.assertIsNone(EvidenceFile(str(path)).get('AAPL',now))
        self.assertIsNone(EvidenceFile().get('MISSING',now))
    def test_missing_fundamentals_and_earnings_exclude_candidates(self):
        row=dict(ticker='AAPL',price=100,sma50=90,sma200=80,rsi=55,atr_pct=.02,average_dollar_volume=30000000,relative_strength=.05,return_20d=.1,source_references=['bars'])
        candidates,rejections=screen([row],Mock(get=Mock(return_value=None)),ResearchConfig(),datetime.now(timezone.utc))
        self.assertFalse(candidates);self.assertIn('fundamentals',rejections[0]['reasons'])
    def test_slack_webhook_rejects_external_hosts(self):
        self.assertTrue(validate_webhook('https://hooks.slack.com/services/T/B/TEST'))
        for url in ['http://hooks.slack.com/services/T/B/X','https://evil.test/services/T/B/X','https://hooks.slack.com.evil.test/services/X']:
            with self.assertRaises(ValueError):validate_webhook(url)
    def test_saved_ai_settings_override_environment_and_require_key(self):
        with patch.dict(os.environ,{'AI_ENABLED':'true','ANTHROPIC_API_KEY':'server-key'}):
            self.assertFalse(ResearchConfig.from_env(settings={'ai_enabled':True,'ai_api_key':''}).enabled)
            self.assertFalse(ResearchConfig.from_env(settings={'ai_enabled':False,'ai_api_key':'user-key'}).enabled)
            self.assertTrue(ResearchConfig.from_env(settings={'ai_enabled':True,'ai_api_key':'user-key'}).enabled)

    def test_malta_schedule_and_model_rates(self):
        from research.models import MODELS
        calendar=ExchangeCalendar(lambda start,end:[{'date':start,'open':'09:30','close':'16:00'}])
        from zoneinfo import ZoneInfo
        schedule=calendar.session('2026-10-26').schedule(ResearchConfig())
        self.assertEqual(schedule['premarket'].astimezone(ZoneInfo('Europe/Malta')).strftime('%H:%M'),'13:30')
        self.assertEqual(schedule['entry'].astimezone(ZoneInfo('Europe/Malta')).strftime('%H:%M'),'15:00')
        self.assertEqual(schedule['postmarket'].astimezone(ZoneInfo('Europe/Malta')).strftime('%H:%M'),'21:15')
        later=calendar.session('2026-11-02').schedule(ResearchConfig())
        self.assertEqual(later['entry'].astimezone(ZoneInfo('Europe/Malta')).strftime('%H:%M'),'16:00')
        for model,rates in MODELS.items():
            config=ResearchConfig.from_env(settings={'ai_model':model,'ai_enabled':False,'ai_api_key':''})
            self.assertEqual(config.input_per_million,rates['input_per_million'])
            self.assertEqual(config.output_per_million,rates['output_per_million'])

    def test_provider_config_has_no_implicit_live_mode(self):
        with patch.dict(os.environ,{'AI_ENABLED':'true','MARKET_TIMEZONE':'America/New_York'}):
            self.assertTrue(ResearchConfig.from_env().enabled)
        with patch.dict(os.environ,{'MAX_AI_COST_USD_PER_DAY':'NaN'}):
            with self.assertRaises(ValueError):ResearchConfig.from_env()

HAVE_DEPS=all(importlib.util.find_spec(n) is not None for n in ('pydantic','fastapi','alpaca_trade_api'))
@unittest.skipUnless(HAVE_DEPS,'Full research dependencies required in candidate image')
class ResearchAITests(ResearchCoreTests):
    def setUp(self):
        super().setUp()
        from research.provider import ModelReply
        self.now=datetime.now(timezone.utc)
        self.snapshot=dict(ticker='AAPL',price=100,data_timestamp=self.now.isoformat(),source_references=['alpaca:daily:AAPL'])
        self.item=dict(ticker='AAPL',action='BUY',analysis_timestamp=self.now.isoformat(),data_timestamp=self.now.isoformat(),summary='Supported trend',
            bullish_factors=['trend'],bearish_factors=[],relevant_catalysts=[],identified_risks=['earnings'],thesis_invalidation_conditions=['trend fails'],
            relevant_source_references=['alpaca:daily:AAPL'],model_name=ResearchConfig.model,analysis_version='1')
        self.provider=Mock();self.provider.complete.return_value=ModelReply(json.dumps(dict(recommendations=[self.item],summary='Watch trend')),100,100)
        self.config=replace(ResearchConfig(),enabled=True)
    def service(self):
        from research.service import AIService
        return AIService(self.db,self.config,self.provider)
    def test_valid_json_cache_and_material_change(self):
        service=self.service()
        self.assertIsNotNone(service.evaluate('premarket',{'AAPL':self.snapshot},{},self.now))
        self.assertIsNotNone(service.evaluate('premarket',{'AAPL':self.snapshot},{},self.now+timedelta(seconds=1)))
        self.assertEqual(self.provider.complete.call_count,1)
        self.assertIsNotNone(service.evaluate('premarket',{'AAPL':{**self.snapshot,'news_version':'new'}},{},self.now))
        self.assertEqual(self.provider.complete.call_count,2)
    def test_budget_blocks_before_provider(self):
        self.config=replace(self.config,dollars=0)
        self.assertIsNone(self.service().evaluate('entry',{'AAPL':self.snapshot},{},self.now))
        self.provider.complete.assert_not_called()
    def test_provider_failure_denies_and_cooldown_prevents_retry(self):
        self.provider.complete.side_effect=TimeoutError()
        service=self.service()
        self.assertIsNone(service.evaluate('entry',{'AAPL':self.snapshot},{},self.now))
        self.assertIsNone(service.evaluate('entry',{'AAPL':self.snapshot},{},self.now))
        self.assertEqual(self.provider.complete.call_count,1)
        self.assertGreater(self.db.usage(self.now.astimezone(ET).date().isoformat())['cost'],0)
    def test_malformed_stale_unsupported_and_contradictory_outputs_rejected(self):
        from research.schemas import validate_report
        variants=[{**self.item,'action':'EXECUTE'},{**self.item,'ticker':'UNKNOWN'},
                  {**self.item,'analysis_timestamp':(self.now-timedelta(hours=1)).isoformat()},
                  {**self.item,'relevant_source_references':['invented-source']},{**self.item,'arbitrary_command':'buy'}]
        for item in variants:
            with self.assertRaises(ValueError):validate_report(json.dumps(dict(recommendations=[item],summary='x')),'entry',{'AAPL':self.snapshot},self.config.model,self.now)
        with self.assertRaises(ValueError):validate_report(json.dumps(dict(recommendations=[self.item],summary='x')),'entry',{'AAPL':{**self.snapshot,'missing_required_evidence':['earnings']}},self.config.model,self.now)
    def test_zero_qualifying_stocks_is_valid(self):
        from research.schemas import validate_report
        result=validate_report('{"recommendations":[],"summary":"No qualifying stocks"}','premarket',{},self.config.model,self.now)
        self.assertEqual(result.recommendations,[])
    def test_exposure_spread_staleness_and_unknown_sector_fail_closed(self):
        from research.gate import deterministic_entry
        snapshot={'latestQuote':{'bp':100,'ap':100.1,'t':self.now.isoformat()}}
        watch=dict(ticker='AAPL',sector='Technology',fundamentals={'sales_growth':.1},next_earnings=(self.now+timedelta(days=30)).date().isoformat(),average_dollar_volume=30000000,atr_pct=.02)
        portfolio=dict(account=dict(equity='10000',buying_power='20000',status='ACTIVE'),positions=[],sectors={})
        self.assertTrue(deterministic_entry(snapshot,portfolio,watch,self.config,1000,self.now)['allowed'])
        self.assertFalse(deterministic_entry(snapshot,portfolio,watch,self.config,7000,self.now)['allowed'])
        self.assertFalse(deterministic_entry({'latestQuote':{**snapshot['latestQuote'],'t':(self.now-timedelta(minutes=2)).isoformat()}},portfolio,watch,self.config,1000,self.now)['allowed'])
        self.assertFalse(deterministic_entry(snapshot,portfolio,{**watch,'sector':None},self.config,1000,self.now)['allowed'])
    def test_gate_is_nonblocking_denies_unknown_and_prevents_duplicate_orders(self):
        from research.gate import permit_entry, setup_key
        now=self.now;day=now.astimezone(ET).date().isoformat();watch={**self.snapshot,'snapshot_version':'1','regime':'uptrend'}
        with patch.dict(os.environ,{'AI_ENABLED':'true','TRADING_MODE':'paper','NEXLARA_RESEARCH_DB':str(self.db.path),'NEXLARA_ACCOUNT_SCOPE':'account'}):
            self.assertFalse(permit_entry('AAPL','rsi',100,1,now)[0])
            self.db.put('session','account:'+day,dict(entry=(now-timedelta(hours=1)).isoformat(),close=(now+timedelta(hours=1)).isoformat()))
            self.db.put('watchlist','account:'+day,{'AAPL':watch})
            key=setup_key('AAPL','rsi',100,watch,day)
            self.db.put('entry_decision',key,{'action':'BUY'},now.timestamp()+60)
            self.db.put('entry_check',key,dict(allowed=True,price=100,spread_bps=10,max_notional=101,portfolio_room=1000,sector_room=1000,broker_symbols=[]),now.timestamp()+30)
            self.assertTrue(permit_entry('AAPL','rsi',100,1,now)[0])
            self.assertFalse(permit_entry('AAPL','rsi',100,1,now)[0])
        with patch.dict(os.environ,{'AI_ENABLED':'false'}):self.assertTrue(permit_entry('AAPL','rsi',100,1,now)[0])
    def test_managed_gate_disables_ai_immediately_when_saved_key_removed(self):
        from research.gate import permit_entry
        with patch.dict(os.environ,{'NEXLARA_MANAGED_AI':'true','AI_ENABLED':'true'}),patch('backend.settings_store.SettingsStore.read',return_value={'ai_enabled':False,'ai_api_key':''}):
            self.assertTrue(permit_entry('AAPL','rsi',100,1,self.now)[0])

    def test_managed_provider_never_falls_back_to_environment_after_removal(self):
        from research.provider import AnthropicProvider
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'server-key'}),patch('backend.settings_store.SettingsStore.read',return_value={'ai_enabled':False,'ai_api_key':''}),patch('anthropic.Anthropic') as sdk:
            with self.assertRaises(RuntimeError):AnthropicProvider(self.config,'old-key',managed=True).complete('system','payload',100)
            sdk.assert_not_called()

    def test_modern_model_omits_unsupported_sampling_parameters(self):
        from research.provider import AnthropicProvider
        from types import SimpleNamespace
        response=SimpleNamespace(stop_reason='end_turn',content=[SimpleNamespace(type='text',text='{}')],usage=SimpleNamespace(input_tokens=10,output_tokens=10))
        with patch('anthropic.Anthropic') as sdk:
            sdk.return_value.messages.create.return_value=response
            AnthropicProvider(replace(self.config,model='claude-sonnet-5-5'),'test-key').complete('system','payload',100)
            kwargs=sdk.return_value.messages.create.call_args.kwargs
            self.assertNotIn('temperature',kwargs)
            self.assertEqual(kwargs['model'],'claude-sonnet-5-5')

    def test_pending_order_exposure_is_checked_without_requiring_a_flat_account(self):
        from research.gate import deterministic_entry
        snapshot={'latestQuote':{'bp':100,'ap':100.1,'t':self.now.isoformat()}}
        watch=dict(ticker='AAPL',sector='Technology',fundamentals={'growth':.1},next_earnings=(self.now+timedelta(days=30)).date().isoformat(),average_dollar_volume=30000000,atr_pct=.02)
        portfolio=dict(account=dict(equity=10000,buying_power=20000,status='ACTIVE'),positions=[],sectors={'MSFT':'Technology'},pending_orders=[dict(symbol='MSFT',side='buy',qty='40',filled_qty='0',limit_price='100')])
        result=deterministic_entry(snapshot,portfolio,watch,self.config,100,self.now)
        self.assertFalse(result['allowed']);self.assertIn('sector_exposure',result['reasons'])

    def test_live_ai_entry_never_enabled_by_recommendation(self):
        from research.gate import permit_entry
        with patch.dict(os.environ,{'AI_ENABLED':'true','TRADING_MODE':'live'}):self.assertFalse(permit_entry('AAPL','rsi',100,1,self.now)[0])
    def test_protective_exit_does_not_call_ai(self):
        import main as engine
        from risk_manager import LivePosition
        # Exercise the real adaptive exit path, not the retired s1 exit hook.
        # Missing ATR/EMA data and an unavailable AI service must not veto a stop.
        for strategy in engine.scalp_exits.INTRADAY:
            side='short' if strategy=='EMA_VWAP_SHORT' else 'long'
            with self.subTest(strategy=strategy):
                position=LivePosition(symbol='AAPL',strategy=strategy,side=side,
                    entry_price=100,qty=1,entry_time=self.now.isoformat(),
                    stop_loss=105 if side=='short' else 95,take_profit=0)
                row={'Close':110 if side=='short' else 90}
                with patch.multiple(engine,risk_mgr=Mock(positions={'AAPL':position}),data_feed=Mock(get_latest_5m=Mock(return_value=row))),patch.object(engine,'now_et',return_value=self.now),patch.object(engine,'_execute_exit') as close,patch.object(engine,'_execute_cover') as cover,patch.object(engine,'permit_entry',side_effect=RuntimeError('AI unavailable')) as ai:
                    engine._check_exits()
                    (cover if side=='short' else close).assert_called_once_with('AAPL','scalp_stop')
                    (close if side=='short' else cover).assert_not_called()
                    ai.assert_not_called()
    def test_idempotent_client_id_reaches_existing_broker_adapter(self):
        from order_manager import OrderManager
        api=Mock();manager=OrderManager(api,Mock(),Mock())
        manager._submit_limit_order('AAPL',1,'buy',100,client_order_id='nx-test')
        self.assertEqual(api.submit_order.call_args.kwargs['client_order_id'],'nx-test')


    def test_worker_batches_signals_and_does_not_retry_unchanged_failure(self):
        from research.worker import ResearchWorker
        from research.provider import ModelReply
        from types import SimpleNamespace
        day=self.now.astimezone(ET).date().isoformat()
        watch=dict(price=100,ticker='AAPL',data_timestamp=self.now.isoformat(),source_references=['alpaca:daily:AAPL'],regime='uptrend',snapshot_version='1',material_digest='same',sector='Technology',fundamentals={'growth':.1},next_earnings=(self.now+timedelta(days=30)).date().isoformat(),average_dollar_volume=30000000,atr_pct=.02)
        items=[]
        for symbol in ('AAPL','MSFT'):
            row={**watch,'ticker':symbol,'source_references':['alpaca:daily:'+symbol]}
            payload=dict(ticker=symbol,strategy='TREND_SWING',price=100,qty=1,scope='account',watch=row,signal_timestamp=self.now.isoformat())
            self.db.queue_signal(symbol,day,symbol,'TREND_SWING',payload)
            self.db.put('material','account:'+symbol,{'digest':'same'},self.now.timestamp()+300)
            items.append({**self.item,'ticker':symbol,'relevant_source_references':row['source_references']})
        self.provider.complete.return_value=ModelReply(json.dumps(dict(recommendations=items,summary='Two candidates')),100,100)
        data=Mock();data.snapshot.return_value={'latestQuote':{'bp':100,'ap':100.1,'t':self.now.isoformat()}}
        data.get.return_value={'tradable':True,'status':'active'}
        worker=ResearchWorker(self.db,self.config,data,Mock(),self.provider,'account')
        worker.portfolio=Mock(return_value=dict(account=dict(equity=10000,buying_power=20000,status='ACTIVE'),positions=[],sectors={}))
        worker.entries(self.now,SimpleNamespace(day=day));worker.entries(self.now,SimpleNamespace(day=day))
        self.assertEqual(self.provider.complete.call_count,1)
        self.assertEqual(self.db.get('entry_decision','AAPL')['action'],'BUY')
        self.assertEqual(self.db.get('entry_decision','MSFT')['action'],'BUY')

    def test_postmarket_early_close_runs_once_after_close_plus_delay(self):
        from research.worker import ResearchWorker
        data=Mock();data.calendar.return_value=[{'date':'2026-11-27','open':'09:30','close':'13:00'}]
        worker=ResearchWorker(self.db,replace(self.config,premarket=False),data,Mock(),self.provider,'account')
        worker.research=Mock(return_value=True)
        worker.tick(datetime(2026,11,27,13,14,tzinfo=ET));worker.research.assert_not_called()
        worker.tick(datetime(2026,11,27,13,15,tzinfo=ET))
        worker.tick(datetime(2026,11,27,13,20,tzinfo=ET));self.assertEqual(worker.research.call_count,1)


    def test_watchlist_data_handoff_reuses_existing_feed_without_http(self):
        from data_feed import DataFeed
        from research.handoff import merge_watchlist
        now=self.now;day=now.astimezone(ET).date().isoformat();api=Mock();feed=DataFeed(api)
        intraday=[dict(t=(now-timedelta(minutes=5*(100-i))).isoformat(),o=100,h=102,l=98,c=100+i*.01,v=10000) for i in range(100)]
        daily=[dict(t=(now-timedelta(days=220-i)).isoformat(),o=100,h=102,l=98,c=100+i*.01,v=1000000) for i in range(220)]
        self.db.put('watchlist','account:'+day,{'NEW':{'ticker':'NEW'}})
        self.db.put('watch_bars','account:'+day+':NEW',dict(intraday=intraday,daily=daily))
        with patch.dict(os.environ,{'AI_ENABLED':'true'}):
            result=merge_watchlist(feed,str(self.db.path),'account',now)
        self.assertEqual(result,['NEW']);self.assertIn('NEW',feed.indicators_5m);self.assertIn('sma200',feed.indicators_daily['NEW'].columns)
        api.get_bars.assert_not_called()

class ReplayTests(unittest.TestCase):
    def test_abcd_replay_does_not_manufacture_missing_ai_decisions(self):
        from research.evaluate import compare
        trade=dict(id='1',ticker='AAPL',qty=10,side='long',signal_time='2026-01-05T14:35:00Z',entry_time='2026-01-05T15:00:00Z',exit_time='2026-01-06T20:00:00Z',entry_fill=100,exit_fill=110)
        data=dict(point_in_time_attested=True,initial_equity=10000,trades=[trade],daily_marks=[{'timestamp':'2026-01-05T21:00:00Z','prices':{'AAPL':100}},{'timestamp':'2026-01-06T21:00:00Z','prices':{'AAPL':110}}],benchmark_prices=[{'timestamp':'2026-01-05T21:00:00Z','price':100},{'timestamp':'2026-01-06T21:00:00Z','price':101}])
        output=compare(data)['comparisons']
        self.assertEqual(output['A']['trade_count'],1);self.assertEqual(output['B']['trade_count'],0)
        self.assertEqual(output['C']['total_return'],output['D']['total_return'])
        trade['premarket_decision']=dict(action='BUY',observed_at='2026-01-06T12:00:00Z',data_as_of='2026-01-05T21:00:00Z')
        self.assertEqual(compare(data)['comparisons']['B']['trade_count'],0)
    def test_replay_rejects_future_signal_and_missing_marks(self):
        from research.evaluate import replay
        trade=dict(id='1',ticker='AAPL',qty=1,signal_time='2026-01-06T00:00:00Z',entry_time='2026-01-05T15:00:00Z',exit_time='2026-01-07T20:00:00Z',entry_fill=100,exit_fill=110)
        with self.assertRaises(ValueError):replay([trade],[],10000,'A')
