"""Auditable research outcomes and selection explanations; all providers are fakes."""
import json
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from research.calendar import ET
from research.company import CachedEvidence, CompanyResearch, CompanyValidationError, validate_company
from research.config import ResearchConfig
from research.data import screen
from research.db import ResearchDB
from research.diagnostics import research_diagnostics, empty_summary
from research.provider import ModelReply


class ResearchDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.db=ResearchDB(Path(self.temp.name)/'research.sqlite3')
        self.now=datetime.now(timezone.utc);self.day=self.now.astimezone(ET).date().isoformat()
        self.config=replace(ResearchConfig(),prototype=True,candidates=3,dollars=.2)
        self.url='https://investor.example.com/results'
        self.report=dict(ticker='META',as_of=(self.now-timedelta(days=2)).isoformat(),sector='Technology',
                         next_earnings=(self.now+timedelta(days=30)).date().isoformat(),earnings_source=self.url,
                         facts=[dict(metric='revenue',value='USD 10 billion',period='Q3',source=self.url)],
                         summary='Company summary',risks=[],sources=[self.url])
        self.reply=ModelReply(json.dumps(self.report),1000,500,2,[self.url],True,'end_turn')
        self.provider=Mock();self.provider.research_company.return_value=self.reply
        self.evidence=CachedEvidence(self.db,'account',self.config.model,Mock(get=Mock(return_value=None)))
        self.company=CompanyResearch(self.db,self.config,self.provider,self.evidence)

    def test_validation_distinguishes_exact_reasons(self):
        cases=[('ticker_mismatch',dict(ticker='AAPL')),
               ('financial_date_timezone_missing',dict(as_of=self.now.replace(tzinfo=None).isoformat())),
               ('future_financial_date',dict(as_of=(self.now+timedelta(days=1)).isoformat())),
               ('stale_financial_date',dict(as_of=(self.now-timedelta(days=121)).isoformat())),
               ('missing_sources',dict(sources=[],facts=[],earnings_source=None,next_earnings=None)),
               ('unretrieved_sources',dict(sources=['https://unretrieved.example.com'])),
               ('invalid_earnings_date',dict(next_earnings='2026-99-99')),
               ('past_earnings_date',dict(next_earnings=(self.now-timedelta(days=1)).date().isoformat())),
               ('missing_earnings_source',dict(earnings_source=None))]
        for code,changes in cases:
            with self.subTest(code=code):
                reply=replace(self.reply,text=json.dumps({**self.report,**changes}))
                with self.assertRaises(CompanyValidationError) as caught:validate_company(reply,'META',self.now)
                self.assertEqual(caught.exception.reason['code'],code)
                self.assertTrue(caught.exception.reason['message'])

    def test_schema_diagnostics_omit_raw_values(self):
        reply=replace(self.reply,text=json.dumps({**self.report,'facts':'PRIVATE-RESPONSE-CONTENT'}))
        with self.assertRaises(CompanyValidationError) as caught:validate_company(reply,'META',self.now)
        reason=caught.exception.reason
        self.assertEqual(reason['code'],'invalid_report_schema')
        self.assertEqual(reason['details']['fields'][0]['field'],'facts')
        self.assertNotIn('PRIVATE-RESPONSE-CONTENT',json.dumps(reason))

    def test_output_limit_is_saved_with_usage_and_not_retried(self):
        self.reply.complete=False;self.reply.stop_reason='max_tokens'
        self.assertIsNone(self.company.refresh('META',100,[],self.now))
        self.assertIsNone(self.company.refresh('META',100,[],self.now))
        self.provider.research_company.assert_called_once()
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        outcome=diagnostic['company_results'][0]
        self.assertEqual(outcome['status'],'rejected')
        self.assertEqual(outcome['reason']['code'],'incomplete_response')
        self.assertEqual(outcome['reason']['details']['stop_reason'],'max_tokens')
        self.assertGreater(outcome['cost'],0)
        self.assertIn('META',empty_summary(diagnostic))
        self.assertIn('output-token limit',empty_summary(diagnostic))

    def test_provider_failure_never_records_sensitive_exception_text(self):
        self.provider.research_company.side_effect=TimeoutError('PRIVATE-API-KEY')
        self.company.refresh('META',100,[],self.now)
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        self.assertNotIn('PRIVATE-API-KEY',json.dumps(diagnostic))
        self.assertEqual(diagnostic['company_results'][0]['reason']['code'],'provider_request_failed')
        self.assertIsNone(diagnostic['company_results'][0]['cost'])

    def test_budget_rejection_is_explicit_and_does_not_call_provider(self):
        self.db.reserve(self.day,.20,8,.20)
        self.company.refresh('META',100,[],self.now)
        self.provider.research_company.assert_not_called()
        result=research_diagnostics(self.db,'account',self.config.model,self.day)['company_results'][0]
        self.assertEqual(result['reason']['code'],'research_budget_exhausted')
        self.assertEqual(result['cost'],0)

    def test_legacy_failure_stays_unknown_and_does_not_cross_accounts(self):
        key=self.evidence.key('META')
        reservation=self.db.reserve(self.day,.04,8,.2)
        self.db.put('company_attempt',key+':'+self.day,True)
        self.db.settle(reservation,.03,1000,500,'received',searches=2)
        self.db.put('search_usage',reservation,dict(ticker='META',day=self.day,cost=.03,searches=2))
        self.db.event('company_research_failure',key,dict(type='ValueError'))
        self.db.event('company_research_failure','other:'+self.config.model+':AAPL',dict(type='ValueError'))
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        self.assertEqual(len(diagnostic['company_results']),1)
        result=diagnostic['company_results'][0]
        self.assertEqual(result['reason']['code'],'legacy_validation_reason_unavailable')
        self.assertEqual(result['cost'],.03)
        self.assertIn('exact validation reason were not saved',result['reason']['message'])

    def test_unscanned_meta_is_not_misreported_as_rejected(self):
        self.db.put('universe','account:'+self.day,['AAPL','ACN','CRL','CTSH','DYLD'])
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        self.assertIn('META',diagnostic['coverage']['core_not_scanned'])
        self.assertIn('AAPL',diagnostic['coverage']['core_included'])
        self.assertIn('no screening verdict',diagnostic['messages'][0])
        self.assertEqual(diagnostic['screening'],{})

    def test_saved_technical_shortlist_preserves_scores_and_metrics(self):
        row=dict(ticker='META',score=42.,price=100.,return_20d=.1,relative_strength=.05)
        self.db.put('technical_screening','account:'+self.day,dict(candidates=[row],available=10,rejections=[]))
        diagnostic=research_diagnostics(self.db,'account',self.config.model,self.day)
        self.assertEqual(diagnostic['shortlist'][0]['score'],42)
        self.assertIn('SPY',diagnostic['selection_rule'])

    def test_api_explains_legacy_report_without_rewriting_history(self):
        import asyncio
        from backend import managed
        key='account:'+self.day+':premarket'
        original='No qualifying candidates or reviewable holdings; no AI ranking call was made.'
        self.db.put('daily_report',key,dict(recommendations=[],summary=original))
        self.db.event('company_research_failure',self.evidence.key('META'),dict(type='ValueError'))
        settings=dict(ai_enabled=False,ai_api_key='',paper_account_id='account')
        with patch.object(managed,'store',Mock(read=Mock(return_value=settings))),patch('research.gate.db_path',return_value=str(self.db.path)),patch.object(managed,'local_schedule',return_value={}):
            result=asyncio.run(managed.research_status())
        self.assertIn('META',result['reports'][0]['payload']['summary'])
        self.assertIn('not saved',result['reports'][0]['payload']['summary'])
        self.assertEqual(self.db.get('daily_report',key)['summary'],original)

    def test_failed_worker_report_preserves_technical_shortlist_and_exact_reason(self):
        from research.worker import ResearchWorker
        from research.calendar import ExchangeCalendar
        now=self.now;previous=now-timedelta(days=1)
        data=Mock();data.universe.return_value=['META'];data.daily.return_value={}
        data.calendar.side_effect=lambda start,end:[dict(date=end,open='09:30',close='16:00')]
        data.portfolio.return_value=dict(account=dict(equity='5000',cash='5000',buying_power='5000'),positions=[])
        data.get.return_value=[];data.news.return_value=[]
        def summary(symbol,*args):
            return dict(ticker=symbol,price=100.,sma50=95.,sma200=90.,rsi=55.,atr_pct=.02,
                        average_dollar_volume=30000000.,return_20d=.1,relative_strength=.05,
                        data_timestamp=previous.isoformat(),source_references=[])
        self.reply.complete=False;self.reply.stop_reason='max_tokens'
        worker=ResearchWorker(self.db,self.config,data,Mock(get=Mock(return_value=None)),self.provider,'account')
        session=ExchangeCalendar(data.calendar).session(now.astimezone(ET).date())
        with patch('research.worker.summarize_bars',side_effect=summary):
            self.assertTrue(worker.research('premarket',now,session))
        key='account:'+session.day
        report=self.db.get('daily_report',key+':premarket')
        self.assertEqual(report['status'],'research_failed')
        self.assertIn('output-token limit',report['summary'])
        self.assertEqual(self.db.get('technical_screening',key)['candidates'][0]['ticker'],'META')
        self.assertEqual(self.db.get('screening',key)['rejections'][0]['research_outcome']['reason']['code'],'incomplete_response')
        self.provider.complete.assert_not_called()

    def test_screen_explains_each_threshold_and_top_three_cutoff(self):
        policy=replace(self.config,require_fundamentals=False,require_earnings=False)
        good=dict(ticker='META',price=100.,sma50=95.,sma200=90.,rsi=55.,atr_pct=.02,
                  average_dollar_volume=30000000.,return_20d=.1,relative_strength=.05,source_references=[])
        evidence=Mock(get=Mock(return_value=None))
        bad={**good,'price':4.,'sma50':80.,'rsi':90.,'average_dollar_volume':100.,'relative_strength':-.1,'atr_pct':.1}
        _,rejected=screen([bad],evidence,policy,self.now)
        messages=' '.join(r['message'] for r in rejected[0]['reason_details'])
        for phrase in ['Price $4.00','200-day average','20-day average','RSI 90.00','ATR/price 10.00%','relative to SPY']:
            self.assertIn(phrase,messages)
        chosen,rejected=screen([{**good,'ticker':s} for s in ['AAPL','ACN','CRL','META']],evidence,policy,self.now)
        self.assertEqual([r['ticker'] for r in chosen],['AAPL','ACN','CRL'])
        self.assertEqual(rejected[0]['ticker'],'META')
        self.assertEqual(rejected[0]['reasons'],['shortlist_limit'])
        self.assertIn('ranked 4',rejected[0]['reason_details'][0]['message'])


if __name__=='__main__':unittest.main()
