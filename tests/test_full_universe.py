"""Full-market coverage and shortlist-before-AI regressions; no network calls."""
import json
import os
import sys
import tempfile
import unittest
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from research.calendar import ET, ExchangeCalendar
from research.config import ResearchConfig
from research.data import AlpacaResearchData
from research.db import ResearchDB
from research.diagnostics import research_diagnostics
from research.provider import ModelReply
from research.worker import ResearchWorker


class FullUniverseDataTests(unittest.TestCase):
    def test_every_active_tradable_equity_is_included_despite_old_limits(self):
        data=AlpacaResearchData({})
        assets=[dict(symbol=f'A{i:05}',status='active',tradable=True,exchange='NYSE',**{'class':'us_equity'}) for i in range(3500)]
        for symbol,exchange in [('META','NASDAQ'),('NVDA','NASDAQ'),('TSLA','NASDAQ'),('ZZZZ','BATS'),('OTCSTOCK','OTC'),('ETF','NYSEARCA')]:
            assets.append(dict(symbol=symbol,status='active',tradable=True,exchange=exchange))
        assets += [dict(symbol='INACTIVE',status='inactive',tradable=True),
                   dict(symbol='BLOCKED',status='active',tradable=False),
                   dict(symbol='BTC/USD',status='active',tradable=True,**{'class':'crypto'}),
                   dict(symbol='META',status='active',tradable=True)]
        data.get=Mock(return_value=assets)
        with patch.dict(os.environ,{'AI_UNIVERSE_LIMIT':'1','AI_UNIVERSE_SYMBOLS':'A00000'}):
            universe=data.universe()
            config=ResearchConfig.from_env()
        self.assertEqual(len(universe),3506)
        for ticker in ['META','NVDA','TSLA','ZZZZ','OTCSTOCK','ETF']:self.assertIn(ticker,universe)
        for ticker in ['INACTIVE','BLOCKED','BTC/USD']:self.assertNotIn(ticker,universe)
        self.assertFalse(hasattr(config,'universe_limit'))
        data.get.assert_called_once_with('/v2/assets',dict(status='active',asset_class='us_equity'))

    def test_daily_pagination_reaches_late_symbols_and_excludes_next_session(self):
        data=AlpacaResearchData({})
        through=datetime(2026,10,23,8,30,tzinfo=ET)
        data.get=Mock(side_effect=[
            dict(bars={'AAPL':[dict(t='2026-10-23T04:00:00Z')]},next_page_token='page-2'),
            dict(bars={'ZZZZ':[dict(t='2026-10-23T04:00:00Z'),dict(t='2026-10-24T04:00:00Z')]},next_page_token=None)])
        history=data.daily(['AAPL','ZZZZ'],through)
        self.assertEqual(len(history['ZZZZ']),1)
        requests=data.get.call_args_list
        self.assertEqual(requests[1].args[1]['page_token'],'page-2')
        self.assertEqual(requests[1].args[1]['sort'],'asc')
        self.assertLess(datetime.fromisoformat(requests[1].args[1]['end']),datetime(2026,10,24,tzinfo=ET))

    def test_repeated_pagination_token_is_not_treated_as_complete(self):
        data=AlpacaResearchData({})
        data.get=Mock(return_value=dict(bars={},next_page_token='same'))
        with self.assertRaisesRegex(RuntimeError,'Repeated daily-bar pagination'):
            data.daily(['META'],datetime(2026,10,23,tzinfo=ET))
        self.assertEqual(data.get.call_count,2)


class FullUniversePipelineTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=ResearchDB(Path(self.temp.name)/'research.sqlite3')
        self.now=datetime.now(timezone.utc)
        self.previous=self.now-timedelta(days=1)
        self.day=self.now.astimezone(ET).date().isoformat()
        self.key='account:'+self.day
        self.config=replace(ResearchConfig(),enabled=True,prototype=True,validation=False,candidates=3,dollars=.20)
        self.data=Mock();self.data.daily.return_value={}
        self.data.calendar.side_effect=lambda start,end:[dict(date=end,open='09:30',close='16:00')]
        self.data.portfolio.return_value=dict(account=dict(equity='5000',cash='5000',buying_power='5000'),positions=[])
        self.data.get.return_value=[];self.data.news.return_value=[];self.data.snapshot.return_value={}
        self.provider=Mock()
        self.worker=ResearchWorker(self.db,self.config,self.data,Mock(get=Mock(return_value=None)),self.provider,'account')
        self.session=ExchangeCalendar(self.data.calendar).session(self.now.astimezone(ET).date())
        self.seen=[]

    def summary(self,symbol,history,benchmark_return=0):
        self.seen.append(symbol)
        relative={'ZZZZ':.5,'META':.4,'NVDA':.3}.get(symbol,.01)
        return dict(ticker=symbol,price=100.,sma50=95.,sma200=90.,rsi=55.,atr=2.,atr_pct=.02,
                    average_dollar_volume=30000000.,return_20d=.1,return_1d=.01,relative_strength=relative,
                    data_timestamp=self.previous.isoformat(),source_references=['alpaca:daily:'+symbol])

    def configure_provider(self,universe):
        url='https://investor.example.com/results'
        def company(system,payload,maximum):
            # Every market-data symbol and the global shortlist must be saved
            # before the first paid company-research request can start.
            self.assertTrue(set(universe)<=set(self.seen))
            progress=self.db.get('scan_progress',self.key)
            self.assertEqual(progress['status'],'complete')
            self.assertEqual(progress['processed'],len(universe))
            shortlist=self.db.get('technical_screening',self.key)['candidates']
            self.assertEqual([r['ticker'] for r in shortlist],['ZZZZ','META','NVDA'])
            ticker=json.loads(payload)['ticker']
            report=dict(ticker=ticker,as_of=(self.now-timedelta(days=2)).isoformat(),sector='Technology',
                        next_earnings=(self.now+timedelta(days=30)).date().isoformat(),earnings_source=url,
                        facts=[dict(metric='revenue',value='USD 10 billion',period='Q3',source=url)],
                        summary='Sourced company research',risks=[],sources=[url])
            return ModelReply(json.dumps(report),1000,500,2,[url])
        def ranking(system,payload,maximum):
            body=json.loads(payload);context=body['context']
            self.assertEqual(set(body['snapshots']),{'ZZZZ','META','NVDA'})
            items=[]
            for ticker,row in body['snapshots'].items():
                items.append(dict(ticker=ticker,action='BUY',analysis_timestamp=context['analysis_timestamp'],
                    data_timestamp=row['data_timestamp'],summary='Sourced review',bullish_factors=['trend'],bearish_factors=[],
                    relevant_catalysts=[],identified_risks=['earnings'],thesis_invalidation_conditions=['trend breaks'],
                    relevant_source_references=[url],model_name=self.config.model,analysis_version='1'))
            return ModelReply(json.dumps(dict(recommendations=items,summary='Daily shortlist review')),1000,500)
        self.provider.research_company.side_effect=company
        self.provider.complete.side_effect=ranking

    def test_over_3000_symbols_ranked_globally_before_three_ai_requests(self):
        universe=[f'A{i:05}' for i in range(3100)]+['META','MSFT','NVDA','TSLA','ZZZZ']
        self.data.universe.return_value=universe
        self.configure_provider(universe)
        with patch('research.worker.summarize_bars',side_effect=self.summary):
            self.assertTrue(self.worker.research('premarket',self.now,self.session))
        self.data.universe.assert_called_once_with()
        self.assertEqual(self.provider.research_company.call_count,3)
        self.assertEqual(self.provider.complete.call_count,1)
        self.assertEqual({json.loads(call.args[1])['ticker'] for call in self.provider.research_company.call_args_list},{'ZZZZ','META','NVDA'})
        self.assertEqual(set(self.db.get('watchlist',self.key,self.now.timestamp())),{'ZZZZ','META','NVDA'})
        self.assertTrue(all(len(call.args[0])<=100 for call in self.data.daily.call_args_list))
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        self.assertEqual(diagnostic['coverage']['count'],3105)
        self.assertNotIn('META',diagnostic['coverage']['core_not_scanned'])
        self.assertEqual(diagnostic['coverage']['policy'],'all_active_tradable_us_equities')
        self.assertTrue(any('No alphabetical cutoff' in message for message in diagnostic['messages']))
        self.assertEqual(diagnostic['technical_screening']['qualified'],3105)
        # Every passing but lower-ranked stock has an explicit cutoff verdict.
        self.assertEqual(len(diagnostic['technical_screening']['rejections']),3102)
        self.assertEqual(self.db.usage(self.day)['searches'],6)

    def test_late_batch_failure_blocks_all_paid_research(self):
        self.data.universe.return_value=['AAA','BBB','META']
        def daily(symbols,through):
            if symbols==['META']:raise TimeoutError('PRIVATE-TEXT')
            return {}
        self.data.daily.side_effect=daily
        with patch('research.worker.SCAN_BATCH_SIZE',2),patch('research.worker.summarize_bars',side_effect=self.summary):
            with self.assertRaisesRegex(RuntimeError,'no AI shortlist'):
                self.worker.research('premarket',self.now,self.session)
        self.provider.research_company.assert_not_called();self.provider.complete.assert_not_called()
        progress=self.db.get('scan_progress',self.key)
        self.assertEqual(progress['status'],'failed')
        self.assertEqual(progress['processed'],2)
        self.assertNotIn('PRIVATE-TEXT',json.dumps(progress))
        self.assertIsNone(self.db.get('technical_screening',self.key))
        self.assertEqual(self.db.usage(self.day)['calls'],0)

    def test_missing_stale_invalid_and_held_symbols_have_separate_verdicts(self):
        universe=['MISSING','STALE','INVALID','HELD','META']
        def summary(symbol,history,benchmark_return=0):
            if symbol=='MISSING':return None
            if symbol=='INVALID':raise ValueError('bad prices')
            row=self.summary(symbol,history,benchmark_return)
            if symbol=='STALE':row['data_timestamp']=(self.previous-timedelta(days=1)).isoformat()
            return row
        with patch('research.worker.SCAN_BATCH_SIZE',2),patch('research.worker.summarize_bars',side_effect=summary):
            rows,rejections,held=self.worker.scan_summaries(universe,self.previous,self.previous.astimezone(ET).date().isoformat(),0,{'HELD'},'premarket',self.key,{})
        self.assertEqual([r['ticker'] for r in rows],['META'])
        self.assertEqual({r['ticker']:r['reasons'][0] for r in rejections},dict(MISSING='daily_history_unavailable',STALE='stale_daily_data',INVALID='invalid_daily_data'))
        self.assertEqual(held[0]['reasons'],['already_held'])
        progress=self.db.get('scan_progress',self.key)
        self.assertEqual(progress['processed'],5)
        self.assertEqual(progress['data_rejected'],3)
        self.assertEqual(progress['held_excluded'],1)
        self.provider.research_company.assert_not_called()


if __name__=='__main__':unittest.main()
