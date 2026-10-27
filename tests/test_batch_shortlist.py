"""All-candidate comparison, budget limits and evidence-gated worker integration."""
import json
import os
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from research.calendar import ET,ExchangeCalendar
from research.config import ResearchConfig
from research.data import AlpacaResearchData
from research.db import ResearchDB
from research.diagnostics import research_diagnostics,empty_summary
from research.provider import AnthropicProvider,ModelReply
from research.shortlist import BatchShortlist,SCHEMA
from research.worker import ResearchWorker

def row(ticker,stamp):
    return dict(ticker=ticker,price=100.,sma50=95.,sma200=90.,rsi=55.,atr=2.,atr_pct=.02,
        average_dollar_volume=30000000.,return_20d=.1,return_1d=.01,relative_strength=.1,
        data_timestamp=stamp,source_references=['alpaca:daily:'+ticker])
def reply(count,picks):
    return ModelReply(json.dumps(dict(reviewed_count=count,picks=[dict(ticker=s,reason='Balanced trend and liquidity',risk='Earnings and price data need verification') for s in picks],summary='Investigate these; no trade approval.')),1000,400)

class BatchShortlistTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=ResearchDB(Path(self.temp.name)/'research.sqlite3')
        self.now=datetime(2026,10,28,12,30,tzinfo=timezone.utc)
        self.config=replace(ResearchConfig(),enabled=True,prototype=True,batch_review=True,candidates=3,dollars=.2,calls=8)
        self.rows=[row(f'A{i:03}',(self.now-timedelta(days=1)).isoformat()) for i in range(124)]
        self.benchmark=row('SPY',self.rows[0]['data_timestamp'])
        self.provider=Mock();self.provider.shortlist.return_value=reply(124,['A123','A122','A121','A120','A119'])
        self.service=BatchShortlist(self.db,self.config,self.provider,'account')
        self.day=self.now.astimezone(ET).date().isoformat()
    def select(self):return self.service.select(self.rows,self.now,self.benchmark)
    def test_all_124_rows_in_one_prompt_and_only_three_research_slots(self):
        result=self.select();self.assertEqual(result['status'],'complete')
        payload=json.loads(self.provider.shortlist.call_args.args[1])
        self.assertEqual(len(payload['rows']),124)
        self.assertEqual({r[0] for r in payload['rows']},{r['ticker'] for r in self.rows})
        self.assertEqual(result['selected'],['A123','A122','A121'])
        self.assertEqual(len(result['picks']),5);self.assertFalse(result['approval'])
        self.provider.complete.assert_not_called();self.provider.research_company.assert_not_called()
        self.assertLessEqual(result['input_bytes']+1200,self.config.tokens)
        self.assertEqual(self.db.usage(self.day)['searches'],0)
    def test_exact_inputs_cache_across_restart_and_accounts_do_not_share(self):
        first=self.select()
        repeated=BatchShortlist(self.db,self.config,self.provider,'account').select(self.rows,self.now+timedelta(minutes=1),self.benchmark)
        self.assertEqual(repeated['selected'],first['selected']);self.assertTrue(repeated['cache_hit'])
        self.assertEqual(self.provider.shortlist.call_count,1)
        BatchShortlist(self.db,self.config,self.provider,'different').select(self.rows,self.now,self.benchmark)
        self.assertEqual(self.provider.shortlist.call_count,2)
    def test_invalid_responses_charge_once_and_never_approve(self):
        variants=[reply(123,['A123']),reply(124,['UNKNOWN']),reply(124,['A123','A123']),
            replace(reply(124,['A123']),complete=False,stop_reason='max_tokens'),
            replace(reply(124,['A123']),text='PRIVATE MALFORMED MODEL TEXT')]
        for i,value in enumerate(variants):
            with self.subTest(case=i):
                service=BatchShortlist(self.db,self.config,self.provider,'case'+str(i));self.provider.shortlist.return_value=value
                result=service.select(self.rows,self.now,self.benchmark)
                self.assertEqual(result['status'],'failed');self.assertFalse(result['selected'])
                calls=self.provider.shortlist.call_count
                service.select(self.rows,self.now,self.benchmark)
                self.assertEqual(self.provider.shortlist.call_count,calls)
                self.assertNotIn('PRIVATE',json.dumps(result))
    def test_known_fund_cannot_take_company_research_slot(self):
        self.rows[-1]['instrument_hint']='fund_name_match'
        self.assertEqual(self.select()['status'],'failed')
    def test_complete_pool_too_large_is_never_silently_truncated(self):
        self.rows=[row(f'X{i:05}',self.rows[0]['data_timestamp']) for i in range(1000)]
        self.assertEqual(self.select()['status'],'input_too_large')
        self.provider.shortlist.assert_not_called();self.assertEqual(self.db.usage(self.day)['calls'],0)
    def test_budget_exhaustion_and_uncertain_request_do_not_retry(self):
        self.db.reserve(self.day,.2,8,.2)
        self.assertEqual(self.select()['status'],'budget_exhausted');self.provider.shortlist.assert_not_called()
        self.db=ResearchDB(Path(self.temp.name)/'other.sqlite3')
        self.service=BatchShortlist(self.db,self.config,self.provider,'account')
        self.provider.shortlist.side_effect=TimeoutError('PRIVATE provider details')
        result=self.select();self.assertEqual(result['status'],'failed')
        self.assertNotIn('PRIVATE',json.dumps(result));self.assertGreater(self.db.usage(self.day)['cost'],0)
        self.select();self.provider.shortlist.assert_called_once()
    def test_new_inputs_do_not_reuse_prior_picks_or_start_another_paid_attempt(self):
        self.select();self.rows[0]['price']=101
        result=self.select();self.assertEqual(result['status'],'already_attempted')
        self.assertEqual(result['selected'],[]);self.provider.shortlist.assert_called_once()
    def test_api_uses_structured_output_without_web_tools(self):
        response=SimpleNamespace(stop_reason='end_turn',usage=SimpleNamespace(input_tokens=100,output_tokens=20),content=[SimpleNamespace(type='text',text='{}')])
        with patch('anthropic.Anthropic') as client:
            client.return_value.messages.create.return_value=response
            AnthropicProvider(self.config,'fake').shortlist('system','payload',1200,SCHEMA)
            options=client.return_value.messages.create.call_args.kwargs
        self.assertEqual(options['output_config']['format']['schema'],SCHEMA)
        self.assertNotIn('tools',options)
    def test_fund_hint_uses_asset_name_without_excluding_from_universe(self):
        data=AlpacaResearchData({});data.get=Mock(return_value=[dict(symbol='ETHA',name='iShares Ethereum Trust ETF',tradable=True,status='active'),dict(symbol='AAPL',name='Apple Inc Common Stock',tradable=True,status='active')])
        self.assertEqual(data.universe(),['AAPL','ETHA'])
        self.assertEqual(data.asset_metadata['ETHA']['instrument_hint'],'fund_name_match')
        self.assertEqual(data.asset_metadata['AAPL']['instrument_hint'],'unknown')
    def test_managed_defaults_enable_batch_without_enlarging_daily_budget(self):
        settings=dict(ai_enabled=True,ai_api_key='test',ai_model=self.config.model)
        with patch.dict(os.environ,{'AI_PROTOTYPE_MODE':'true','AI_BATCH_REVIEW_ENABLED':'true'}):
            policy=ResearchConfig.from_env(settings=settings)
        self.assertTrue(policy.batch_review);self.assertEqual(policy.dollars,.2)

class BatchWorkerTests(unittest.TestCase):
    setUp=BatchShortlistTests.setUp
    # Integration cases use the same 124-company fixture with a real worker/store.
    def worker(self):
        data=Mock();data.daily.return_value={};data.universe.return_value=[r['ticker'] for r in self.rows]
        data.calendar.side_effect=lambda start,end:[dict(date=end,open='09:30',close='16:00')]
        data.portfolio.return_value=dict(account=dict(equity='100000',cash='100000',buying_power='400000'),positions=[])
        data.get.return_value=[];data.news.return_value=[];data.snapshot.return_value={}
        worker=ResearchWorker(self.db,self.config,data,Mock(get=Mock(return_value=None)),self.provider,'account')
        session=ExchangeCalendar(data.calendar).session(self.now.astimezone(ET).date())
        previous=(self.now-timedelta(days=1)).isoformat()
        def summary(symbol,*args):
            r=row(symbol,previous)
            if symbol.startswith('A') and symbol[1:].isdigit():r['relative_strength']=1-int(symbol[1:])/1000
            return r
        return worker,session,summary
    def test_ai_can_promote_low_technical_rank_and_only_selected_receive_research(self):
        worker,session,summary=self.worker();url='https://investor.example.com/report'
        def company(system,payload,maximum):
            ticker=json.loads(payload)['ticker']
            self.assertEqual(maximum,2400)
            report=dict(ticker=ticker,as_of=(self.now-timedelta(days=2)).isoformat(),sector='Technology',
                next_earnings=(self.now+timedelta(days=30)).date().isoformat(),earnings_source=url,
                facts=[dict(metric='revenue',value='USD 1 billion',period='Q3',source=url)],summary='Sourced',risks=[],sources=[url])
            return ModelReply(json.dumps(report),1000,400,2,[url])
        self.provider.research_company.side_effect=company
        def final(system,payload,maximum):
            body=json.loads(payload);context=body['context'];items=[]
            for symbol,r in body['snapshots'].items():
                items.append(dict(ticker=symbol,action='BUY',analysis_timestamp=context['analysis_timestamp'],data_timestamp=r['data_timestamp'],summary='Sourced',bullish_factors=['trend'],bearish_factors=[],relevant_catalysts=[],identified_risks=['earnings'],thesis_invalidation_conditions=['trend breaks'],relevant_source_references=[url],model_name=self.config.model,analysis_version='1'))
            return ModelReply(json.dumps(dict(recommendations=items,summary='Evidence-complete comparison')),1000,500)
        self.provider.complete.side_effect=final
        with patch('research.worker.summarize_bars',side_effect=summary):
            self.assertTrue(worker.research('premarket',self.now,session))
        self.provider.shortlist.assert_called_once();self.assertEqual(self.provider.research_company.call_count,3)
        self.assertEqual({json.loads(c.args[1])['ticker'] for c in self.provider.research_company.call_args_list},{'A121','A122','A123'})
        self.provider.complete.assert_called_once()
        self.assertEqual(set(self.db.get('watchlist','account:'+self.day,self.now.timestamp())),{'A121','A122','A123'})
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        self.assertEqual(diagnostic['technical_screening']['qualified'],124)
        self.assertEqual(diagnostic['batch_review']['reviewed_count'],124)
        self.assertEqual(self.db.usage(self.day)['searches'],6)
        self.assertLessEqual(self.db.usage(self.day)['cost'],.2)
    def test_failed_batch_never_starts_company_research_or_final_approval(self):
        worker,session,summary=self.worker();self.provider.shortlist.return_value=reply(124,['UNKNOWN'])
        with patch('research.worker.summarize_bars',side_effect=summary):
            self.assertTrue(worker.research('premarket',self.now,session))
        self.provider.research_company.assert_not_called();self.provider.complete.assert_not_called()
        self.assertEqual(self.db.get('watchlist','account:'+self.day),{})
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        self.assertIn('batch comparison did not complete',empty_summary(diagnostic))
