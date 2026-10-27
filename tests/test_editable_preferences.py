"""Editable paper preferences flow into sizing, calendars and research, with risk checks intact."""
import asyncio
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from backend.settings_store import SettingsStore
from backend import managed,main as backend
from research.config import ResearchConfig
from research.calendar import ET,Session
from research.db import ResearchDB
from research.provider import ModelReply
from research.shortlist import BatchShortlist
from research.company import CachedEvidence,CompanyResearch
from research.service import AIService
from risk_manager import RiskManager
import config

class EditablePreferencesTests(unittest.TestCase):
    def test_saved_preferences_accept_values_beyond_old_caps_and_persist(self):
        import httpx
        async def exercise():
            with tempfile.TemporaryDirectory() as directory:
                store=SettingsStore(directory)
                with patch.object(managed,'store',store):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app),base_url='http://testserver') as client:
                        values=dict(max_order_value=250000,position_size_multiplier=.5,max_positions=150,max_position_pct=75,
                            buying_power_reserve_pct=0,max_gross_exposure_pct=800,entry_start='09:30',opening_delay_minutes=0,
                            intraday_close_buffer_minutes=10,scalp_max_hold_minutes=600,ai_daily_budget=10,
                            ai_daily_call_limit=200,ai_request_token_limit=50000,ai_research_slots=30,
                            ai_batch_priority_limit=40,ai_searches_per_company=5,ai_daily_search_limit=200,
                            ai_company_output_tokens=5000,ai_batch_output_tokens=4000,ai_final_output_tokens=6000,
                            ai_premarket_time='07:00',ai_postmarket_delay_minutes=5,ai_min_price=1,ai_rsi_min=20,ai_rsi_max=90)
                        response=await client.put('/api/workspace/settings',json=values)
                        self.assertEqual(response.status_code,200,response.text)
                        saved=SettingsStore(directory).read()
                        for key,value in values.items():self.assertEqual(saved[key],value,key)
                        self.assertEqual(saved['max_daily_loss_pct'],2)
                        self.assertEqual(saved['halt_equity'],4500)
                        policy=ResearchConfig.from_env(settings=saved)
                        self.assertEqual((policy.candidates,policy.batch_priorities,policy.dollars,policy.calls),(30,40,10,200))
                        self.assertEqual((policy.tokens,policy.searches_per_company,policy.daily_searches),(50000,5,200))
                        self.assertTrue(policy.require_fundamentals);self.assertTrue(policy.require_earnings)
        asyncio.run(exercise())
    def test_invalid_combinations_and_risk_bypasses_still_rejected(self):
        import httpx
        async def exercise():
            with tempfile.TemporaryDirectory() as directory,patch.object(managed,'store',SettingsStore(directory)):
                async with httpx.AsyncClient(transport=httpx.ASGITransport(app=backend.app),base_url='http://testserver') as client:
                    for body in [dict(entry_start='25:00'),dict(intraday_close_buffer_minutes=0),
                        dict(ai_daily_budget=-1),dict(ai_rsi_min=80,ai_rsi_max=30),
                        dict(ai_research_slots=10,ai_batch_priority_limit=5),
                        dict(ai_request_token_limit=1000),dict(max_daily_loss_pct=0),
                        dict(halt_equity=5000),dict(close_on_stop=False)]:
                        response=await client.put('/api/workspace/settings',json=body)
                        self.assertEqual(response.status_code,422,(body,response.text))
        asyncio.run(exercise())
    def test_existing_saved_values_are_not_reset_by_schema_upgrade(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(directory)
            store.write(dict(schema_version=5,max_order_value=7500,max_positions=12,position_size_multiplier=8,max_daily_loss_pct=1.5,starting_capital=10000,halt_equity=9000,api_key='test',secret_key='secret'))
            saved=store.read()
            self.assertEqual((saved['max_order_value'],saved['max_positions'],saved['position_size_multiplier']),(7500,12,8))
            self.assertEqual(saved['schema_version'],6);self.assertEqual(saved['ai_daily_budget'],.2)
            self.assertEqual(saved['secret_key'],'secret')
    def test_schedule_uses_preferences_and_actual_early_close(self):
        policy=replace(ResearchConfig(),premarket_time='07:00',entry_start='09:30',opening_minutes=0,postmarket_delay_minutes=5)
        opening=datetime(2026,11,27,9,30,tzinfo=ET);close=opening.replace(hour=13,minute=0)
        times=Session('2026-11-27',opening,close).schedule(policy)
        self.assertEqual(times['entry'],opening)
        self.assertEqual(times['premarket'].hour,7)
        self.assertEqual(times['postmarket'],close+timedelta(minutes=5))
    def test_fractional_multiplier_reduces_size_and_large_settings_keep_broker_ceiling(self):
        account=dict(equity=5000,buying_power=20000,regt_buying_power=10000,multiplier=4)
        acct=SimpleNamespace(get_portfolio_value=lambda:5000,get_buying_power=lambda:20000,
            get_account=lambda:account,get_open_positions=lambda:[],api=SimpleNamespace(list_orders=lambda **_:[]))
        with patch.multiple(config,ALLOCATION_MODE='fill_slots',MAX_ORDER_VALUE=250000,
                MAX_CONCURRENT_POSITIONS=20,POSITION_SIZE_MULTIPLIER=.5,MAX_GROSS_EXPOSURE=8,BUYING_POWER_RESERVE_PCT=0):
            qty,value=RiskManager(acct).calc_position_size(100,'EMA_VWAP')
            self.assertLessEqual(qty*100.05,500);self.assertGreater(value,499)
            with patch.object(config,'POSITION_SIZE_MULTIPLIER',100):
                qty,_=RiskManager(acct).calc_position_size(100,'EMA_VWAP')
                self.assertLessEqual(qty*100.05,20000)
    def test_engine_receives_timing_and_sizing_preferences(self):
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(directory);values=store.read();values.update(entry_start='09:30',opening_delay_minutes=0,intraday_close_buffer_minutes=10,scalp_max_hold_minutes=90,max_order_value=50000)
            store.write(values)
            with patch.object(managed,'store',store),patch.object(backend,'_bot_alive',return_value=False),patch.object(backend.runtime,'start',return_value=SimpleNamespace(poll=lambda:None,pid=42)) as launch,patch.object(backend.asyncio,'sleep',return_value=None):
                asyncio.run(backend.bot_start(backend.BotStartRequest(api_key='fake',secret_key='fake',strategy='ema_vwap')))
            env=launch.call_args.args[2]
            for key,value in [('ENTRY_EVALUATION_START','09:30'),('AI_OPENING_RESTRICTION_MINUTES','0'),('NEXLARA_INTRADAY_CLOSE_BUFFER_MINUTES','10'),('NEXLARA_SCALP_MAX_HOLD_MINUTES','90'),('NEXLARA_MAX_ORDER_VALUE','50000')]:self.assertEqual(env[key],value)
    def test_priority_and_output_limits_are_configurable(self):
        with tempfile.TemporaryDirectory() as directory:
            now=datetime(2026,10,28,12,30,tzinfo=timezone.utc);stamp=(now-timedelta(days=1)).isoformat()
            rows=[dict(ticker=f'A{i}',price=100,return_20d=.1,relative_strength=.1,rsi=55,atr_pct=.02,average_dollar_volume=30000000,sma200=90) for i in range(8)]
            policy=replace(ResearchConfig(),enabled=True,prototype=True,candidates=6,batch_priorities=8,batch_output_tokens=3000,final_output_tokens=6000,tokens=30000)
            provider=Mock();provider.shortlist.return_value=ModelReply(json.dumps(dict(reviewed_count=8,picks=[dict(ticker=r['ticker'],reason='trend',risk='earnings') for r in rows],summary='Research only')),100,100)
            db=ResearchDB(Path(directory)/'research.sqlite3')
            result=BatchShortlist(db,policy,provider,'account').select(rows,now,dict(ticker='SPY',data_timestamp=stamp))
            self.assertEqual(result['status'],'complete');self.assertEqual(len(result['selected']),6)
            self.assertEqual(provider.shortlist.call_args.args[2],3000)
            self.assertEqual(AIService(db,policy,provider).output_limit(),6000)

    def test_late_entries_follow_saved_close_buffer_instead_of_fixed_1530(self):
        import main as engine
        now=datetime(2026,10,28,15,40,tzinfo=ET)
        risk=Mock(positions={});risk.is_halted.return_value=False;risk.is_daily_halted.return_value=False
        feed=Mock();feed.poll_latest_bars.return_value={}
        api=Mock();api.get_clock.return_value=SimpleNamespace(is_open=True,next_close=now.replace(hour=16,minute=0))
        with patch.multiple(engine,api=api,risk_mgr=risk,data_feed=feed,log=Mock(),universe=Mock(all_symbols=lambda:[]),_orb_computed=True),patch.object(engine,'now_et',return_value=now),patch.object(config,'INTRADAY_CLOSE_BUFFER_MINUTES',10),patch('research.handoff.merge_watchlist',return_value=[]),patch('broker_reconciliation.reconcile_broker_state',return_value=({},[])),patch.object(engine,'_check_exits'),patch.object(engine,'_write_state'),patch.object(engine,'_scan_entries') as scan,patch.object(engine,'time_stop_close') as flatten:
            engine.trading_tick();scan.assert_called_once();flatten.assert_not_called()
    def test_company_preferences_reach_provider_and_search_ledger(self):
        with tempfile.TemporaryDirectory() as directory:
            now=datetime(2026,10,28,12,30,tzinfo=timezone.utc);url='https://investor.example.com/results'
            db=ResearchDB(Path(directory)/'research.sqlite3')
            policy=replace(ResearchConfig(),dollars=5,searches_per_company=4,daily_searches=12,company_output_tokens=5000,company_cache_days=0)
            provider=Mock();provider.research_company.return_value=ModelReply(json.dumps(dict(ticker='AAPL',as_of=(now-timedelta(days=1)).isoformat(),sector='Technology',next_earnings=(now+timedelta(days=30)).date().isoformat(),earnings_source=url,facts=[dict(metric='revenue',value='USD 1 billion',period='Q3',source=url)],summary='Verified',risks=[],sources=[url])),1000,500,4,[url])
            evidence=CachedEvidence(db,'account',policy.model,Mock(get=Mock(return_value=None)))
            company=CompanyResearch(db,policy,provider,evidence)
            self.assertIsNotNone(company.refresh('AAPL',100,[],now))
            self.assertEqual(provider.research_company.call_args.args[2],5000)
            self.assertIn('4 web searches',provider.research_company.call_args.args[0])
            self.assertEqual(db.usage(now.astimezone(ET).date().isoformat())['searches'],4)
            self.assertIsNotNone(evidence.get('AAPL',now))
            self.assertIsNone(evidence.get('AAPL',now+timedelta(days=1)))
            disabled=CompanyResearch(db,replace(policy,searches_per_company=0),provider,evidence)
            calls=provider.research_company.call_count
            self.assertIsNone(disabled.refresh('MSFT',100,[],now));self.assertEqual(provider.research_company.call_count,calls)

    def test_managed_percentage_sizing_still_respects_gross_capacity(self):
        acct=SimpleNamespace(get_portfolio_value=lambda:5000,get_buying_power=lambda:20000,get_account=lambda:dict(equity=5000,buying_power=20000,regt_buying_power=10000,multiplier=4),get_open_positions=lambda:[],get_position_count=lambda:0,api=SimpleNamespace(list_orders=lambda **_:[]))
        risk=RiskManager(acct)
        with patch.dict(os.environ,{'NEXLARA_MANAGED_AI':'true','NEXLARA_SIZING_BASIS':'buying_power'}),patch.multiple(config,ALLOCATION_MODE='percentage',POSITION_SIZE_MULTIPLIER=1,MAX_POSITION_PCT=.75,MAX_ORDER_VALUE=250000,MAX_GROSS_EXPOSURE=1,BUYING_POWER_RESERVE_PCT=0):
            qty,value=risk.calc_position_size(100,'EMA_VWAP')
            self.assertLessEqual(qty*100.05,5000)
            self.assertFalse(risk.validate_order('AAPL',100,100,'EMA_VWAP')[0])
