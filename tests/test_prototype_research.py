"""Offline prototype acceptance tests; provider and broker calls are mocked."""
import importlib.util
import json
import os
from dataclasses import replace
from datetime import datetime,timedelta,timezone
from pathlib import Path
from types import SimpleNamespace
import sys
import tempfile
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from research.db import ResearchDB
from research.config import ResearchConfig
from research.calendar import ET

class PrototypeCoreTests(unittest.TestCase):
    def test_managed_defaults_and_cap(self):
        with patch.dict(os.environ,{'AI_PROTOTYPE_MODE':'true','MAX_AI_COST_USD_PER_DAY':'10','MAX_AI_CALLS_PER_DAY':'50'}):
            config=ResearchConfig.from_env(settings={'ai_enabled':True,'ai_api_key':'test'})
        self.assertTrue(config.prototype);self.assertEqual(config.dollars,.20)
        self.assertEqual(config.candidates,3);self.assertFalse(config.validation)
        self.assertEqual(config.calls,8);self.assertEqual(config.company_cache_days,7)
    def test_search_reservations_survive_restart_and_limit_six(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'research.sqlite3';db=ResearchDB(path)
            for _ in range(3):self.assertTrue(db.reserve('day',.04,8,.2,searches=2,max_searches=6))
            db=ResearchDB(path)
            self.assertIsNone(db.reserve('day',.04,8,.2,searches=2,max_searches=6))
            self.assertEqual(db.usage('day')['searches'],6)
    def test_actual_tool_cost_replaces_estimate(self):
        with tempfile.TemporaryDirectory() as directory:
            db=ResearchDB(Path(directory)/'research.sqlite3')
            key=db.reserve('day',.046,8,.2,searches=2,max_searches=6)
            db.settle(key,.016,1000,1000,'received',searches=1)
            self.assertEqual(db.usage('day')['searches'],1)
            self.assertEqual(db.usage('day')['cost'],.016)
    def test_usage_schema_migrates_existing_database(self):
        import sqlite3
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'research.sqlite3'
            with sqlite3.connect(path) as db:
                db.execute('CREATE TABLE usage(id TEXT PRIMARY KEY,day TEXT,reserved REAL,cost REAL,input_tokens INTEGER,output_tokens INTEGER,status TEXT,ts REAL)')
                db.execute("INSERT INTO usage VALUES('old','day',.1,.1,1,1,'received',0)")
            db=ResearchDB(path);self.assertEqual(db.usage('day')['cost'],.1);self.assertEqual(db.usage('day')['searches'],0)

HAVE_DEPS=importlib.util.find_spec('pydantic') is not None and importlib.util.find_spec('fastapi') is not None
@unittest.skipUnless(HAVE_DEPS,'Pydantic dependencies required in candidate image')
class PrototypeAITests(unittest.TestCase):
    def setUp(self):
        from research.company import CachedEvidence,CompanyResearch
        from research.provider import ModelReply
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=ResearchDB(Path(self.temp.name)/'research.sqlite3');self.now=datetime.now(timezone.utc)
        self.config=replace(ResearchConfig(),prototype=True,enabled=True,dollars=.20,candidates=3,validation=False)
        self.url='https://investor.example.com/earnings'
        self.report=dict(ticker='AAPL',as_of=(self.now-timedelta(days=2)).isoformat(),sector='Technology',next_earnings=(self.now+timedelta(days=50)).date().isoformat(),earnings_source=self.url,
            facts=[dict(metric='revenue',value='USD 10 billion',period='latest quarter',source=self.url)],summary='Sourced research',risks=['valuation'],sources=[self.url])
        self.provider=Mock();self.provider.research_company.return_value=ModelReply(json.dumps(self.report),1000,500,2,[self.url])
        self.evidence=CachedEvidence(self.db,'account',self.config.model,Mock(get=Mock(return_value=None)))
        self.research=CompanyResearch(self.db,self.config,self.provider,self.evidence)
    def refresh(self,now=None,price=100,news=None):return self.research.refresh('AAPL',price,news or [],now or self.now)
    def test_cache_reused_across_restart_and_expires_seven_days(self):
        from research.company import CompanyResearch
        self.assertIsNotNone(self.refresh())
        restarted=CompanyResearch(self.db,self.config,self.provider,self.evidence)
        self.assertIsNotNone(restarted.refresh('AAPL',101,[],self.now+timedelta(days=6)))
        self.provider.research_company.assert_called_once()
        self.assertIsNotNone(restarted.refresh('AAPL',101,[],self.now+timedelta(days=8)))
        self.assertEqual(self.provider.research_company.call_count,2)
    def test_major_news_and_price_invalidate_without_paid_same_day_retry(self):
        self.assertIsNotNone(self.refresh())
        self.assertIsNone(self.refresh(news=[{'headline':'Company cuts earnings guidance','id':'new'}]))
        self.assertIsNone(self.evidence.get('AAPL',self.now))
        self.provider.research_company.assert_called_once()
    def test_price_change_refreshes_on_later_day(self):
        self.refresh();self.refresh(now=self.now+timedelta(days=1),price=106)
        self.assertEqual(self.provider.research_company.call_count,2)
    def test_disappearing_old_news_does_not_trigger_refresh(self):
        self.refresh(news=[{'headline':'Earnings release','id':'old'}])
        self.refresh(now=self.now+timedelta(days=1))
        self.provider.research_company.assert_called_once()
    def test_earnings_window_requires_refresh(self):
        self.report['next_earnings']=(self.now+timedelta(days=4)).date().isoformat()
        self.provider.research_company.return_value.text=json.dumps(self.report)
        self.refresh();self.refresh(now=self.now+timedelta(days=1))
        self.assertEqual(self.provider.research_company.call_count,2)
    def test_unsupported_sources_and_malformed_research_never_cached(self):
        self.provider.research_company.return_value.sources=['https://other.example.com']
        self.assertIsNone(self.refresh());self.assertIsNone(self.evidence.get('AAPL',self.now))
        self.assertGreater(self.db.usage(self.now.astimezone(ET).date().isoformat())['cost'],0)
    def test_timeout_reservation_not_retried(self):
        self.provider.research_company.side_effect=TimeoutError('never log secrets')
        self.assertIsNone(self.refresh());self.assertIsNone(self.refresh())
        self.provider.research_company.assert_called_once()
        self.assertGreater(self.db.usage(self.now.astimezone(ET).date().isoformat())['cost'],.02)
    def test_budget_exhaustion_prevents_company_call(self):
        self.db.reserve(self.now.astimezone(ET).date().isoformat(),.20,8,.20)
        self.assertIsNone(self.refresh());self.provider.research_company.assert_not_called()
    def test_missing_news_invalidates_cache(self):
        self.refresh()
        self.assertIsNone(self.research.refresh('AAPL',100,[],self.now,False))
        self.assertIsNone(self.evidence.get('AAPL',self.now))
    def test_intraday_needs_no_research_but_live_is_rejected(self):
        from research.gate import permit_entry
        with patch.dict(os.environ,{'NEXLARA_MANAGED_AI':'true','TRADING_MODE':'paper'}),patch('research.gate.runtime_policy',return_value=self.config),patch('research.gate.ResearchDB') as db:
            self.assertTrue(permit_entry('AAPL','EMA_VWAP',100,1)[0]);db.assert_not_called()
        with patch.dict(os.environ,{'NEXLARA_MANAGED_AI':'true','TRADING_MODE':'live'}),patch('research.gate.runtime_policy',return_value=self.config):
            self.assertFalse(permit_entry('AAPL','EMA_VWAP',100,1)[0])
    def test_official_provider_limits_tools_and_reports_actual_searches(self):
        from research.provider import AnthropicProvider
        response=SimpleNamespace(stop_reason='end_turn',usage=SimpleNamespace(input_tokens=100,output_tokens=20,server_tool_use=SimpleNamespace(web_search_requests=1)),
            content=[SimpleNamespace(type='text',text='Searching...'),SimpleNamespace(type='web_search_tool_result',content=[SimpleNamespace(type='web_search_result',url=self.url)]),SimpleNamespace(type='text',text=json.dumps(self.report))])
        with patch('anthropic.Anthropic') as client:
            client.return_value.messages.create.return_value=response
            reply=AnthropicProvider(self.config,'fake').research_company('system','payload',1200)
            options=client.return_value.messages.create.call_args.kwargs
        self.assertEqual(options['tools'][0]['max_uses'],2)
        self.assertEqual(reply.searches,1);self.assertEqual(reply.sources,[self.url]);self.assertEqual(json.loads(reply.text)['ticker'],'AAPL')

    def test_worker_screens_three_then_batches_and_reviews_holdings_without_new_search(self):
        from research.worker import ResearchWorker
        from research.provider import ModelReply
        from research.calendar import ExchangeCalendar
        now=self.now
        previous=now-timedelta(days=1)
        previous_date=previous.astimezone(ET).date().isoformat()
        data=Mock()
        data.universe.return_value=['AAPL','MSFT','NVDA','ZZZ']
        data.daily.return_value={}
        data.calendar.side_effect=lambda start,end:[{'date':end,'open':'09:30','close':'16:00'}]
        data.portfolio.return_value={'account':{'equity':'5000','cash':'5000','buying_power':'5000'},'positions':[]}
        data.get.return_value=[];data.news.return_value=[];data.snapshot.return_value={}
        def summary(symbol,bars,benchmark_return=0):
            return dict(ticker=symbol,price=100,sma50=95,sma200=90,rsi=55,atr=2,atr_pct=.02,
                average_dollar_volume=30000000,return_20d=.1,return_1d=.01,relative_strength=.05,
                data_timestamp=previous.isoformat(),source_references=['alpaca:daily:'+symbol])
        def company_reply(system,payload,max_output):
            ticker=json.loads(payload)['ticker']
            return ModelReply(json.dumps({**self.report,'ticker':ticker}),1000,500,2,[self.url])
        def batch_reply(system,payload,max_output):
            body=json.loads(payload);context=body['context'];items=[]
            for ticker,row in body['snapshots'].items():
                items.append(dict(ticker=ticker,action='BUY' if context['task']=='premarket' else 'CONTINUE HOLDING',
                    analysis_timestamp=context['analysis_timestamp'],data_timestamp=row['data_timestamp'],summary='Sourced review',
                    bullish_factors=['trend'],bearish_factors=[],relevant_catalysts=[],identified_risks=['earnings'],
                    thesis_invalidation_conditions=['trend breaks'],relevant_source_references=[self.url],
                    model_name=self.config.model,analysis_version='1'))
            return ModelReply(json.dumps(dict(recommendations=items,summary='Daily review')),1000,500)
        self.provider.research_company.side_effect=company_reply;self.provider.complete.side_effect=batch_reply
        worker=ResearchWorker(self.db,self.config,data,Mock(get=Mock(return_value=None)),self.provider,'account')
        session=ExchangeCalendar(lambda start,end:[{'date':end,'open':'09:30','close':'16:00'}]).session(now.astimezone(ET).date())
        with patch('research.worker.summarize_bars',side_effect=summary),patch.object(worker,'intraday_symbols',return_value=set()):
            self.assertTrue(worker.research('premarket',now,session))
            self.assertEqual(self.provider.research_company.call_count,3)
            self.assertEqual(self.provider.complete.call_count,1)
            self.assertEqual(len(self.db.get('watchlist','account:'+session.day,now.timestamp())),3)
            # Simulate a completed session and one held, already researched stock.
            previous=now
            data.portfolio.return_value['positions']=[{'symbol':'AAPL','market_value':'100','unrealized_pl':'1','side':'long'}]
            self.assertTrue(worker.research('postmarket',now,session))
        self.assertEqual(self.provider.research_company.call_count,3)
        self.assertEqual(self.provider.complete.call_count,2)
        final=json.loads(self.provider.complete.call_args.args[1])
        self.assertEqual(set(final['snapshots']),{'AAPL'})
        self.assertEqual(self.db.usage(now.astimezone(ET).date().isoformat())['searches'],6)
