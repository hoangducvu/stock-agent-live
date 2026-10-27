"""Pure signal/risk tests plus full-dependency engine wiring tests."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch, Mock
from datetime import datetime, timedelta, timezone
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
sys.path.insert(0,'/app')
import config
import strategy_selector
import strategy_extra
import news_catalysts
from strategy_catalog import IDS, NAMES
from risk_manager import RiskManager

class MultiStrategyTests(unittest.TestCase):
    def test_every_checked_strategy_is_evaluated(self):
        with patch.dict(os.environ, {'STRATEGIES':json.dumps(IDS), 'STRATEGY':'ema_vwap'}):
            choices=strategy_selector.get_applicable_strategies('AAPL',None,shorts_enabled=True)
        self.assertEqual({name for name,_ in choices},set(NAMES.values()))

    def test_unchecked_strategies_and_pdt_intraday_are_excluded(self):
        with patch.dict(os.environ, {'STRATEGIES':json.dumps(['orb','rsi_fade'])}):
            choices=strategy_selector.get_applicable_strategies('AAPL',None,can_day_trade=False,shorts_enabled=True)
        self.assertEqual([name for name,_ in choices],['RSI_FADE'])

    def test_sizing_uses_available_buying_power_and_cap(self):
        account=SimpleNamespace(get_portfolio_value=lambda:5000,get_buying_power=lambda:20000)
        with patch.dict(os.environ,{'NEXLARA_SIZING_BASIS':'buying_power'}),patch.object(config,'MAX_POSITION_PCT',.05),patch.object(config,'MAX_ORDER_VALUE',1000):
            qty,amount=RiskManager(account).calc_position_size(100)
        self.assertGreater(amount,999)
        self.assertLessEqual(qty*100.05,1000)

    def test_intraday_data_must_be_recent_and_timezone_aware(self):
        now=datetime.now(timezone.utc)
        self.assertTrue(strategy_extra.fresh_intraday(SimpleNamespace(name=now-timedelta(minutes=5)),now))
        self.assertFalse(strategy_extra.fresh_intraday(SimpleNamespace(name=now-timedelta(minutes=30)),now))
        self.assertFalse(strategy_extra.fresh_intraday(SimpleNamespace(name=now.replace(tzinfo=None)),now))
        self.assertFalse(strategy_extra.fresh_intraday(None,now))

    def test_pullback_and_breakout_positive_and_negative_signals(self):
        row=dict(Close=103,Low=100,ema9=101,ema21=100,ema55=99,vwap=100,Volume=200,vol_ma=100,previous_close=100,prior_high20=102)
        self.assertEqual(strategy_extra.pullback(row),'BUY')
        self.assertEqual(strategy_extra.channel_breakout(row),'BUY')
        self.assertEqual(strategy_extra.channel_breakout({**row,'previous_close':103}),'NONE')
        self.assertEqual(strategy_extra.pullback({**row,'Volume':20}),'NONE')
        self.assertEqual(strategy_extra.channel_breakout({**row,'Close':float('nan')}),'NONE')

    def test_news_requires_fresh_catalyst_and_rejects_negation(self):
        now=datetime.now(timezone.utc)
        story=dict(headline='Acme raises guidance after earnings beat',created_at=now.isoformat())
        self.assertTrue(news_catalysts.eligible(story,now))
        self.assertFalse(news_catalysts.eligible({**story,'headline':'Acme may raise guidance'},now))
        self.assertFalse(news_catalysts.eligible({**story,'headline':'Acme denies FDA approval rumor'},now))
        self.assertFalse(news_catalysts.eligible({**story,'created_at':(now-timedelta(hours=5)).isoformat()},now))

    def test_news_needs_price_volume_confirmation(self):
        row=dict(Open=100,Close=103,ema9=102,ema21=101,vwap=101,Volume=200,vol_ma=100)
        self.assertEqual(strategy_extra.news_momentum(row),'BUY')
        self.assertEqual(strategy_extra.news_momentum({**row,'Volume':10}),'NONE')

    def test_news_intent_survives_restart_and_corruption_blocks_it(self):
        with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{'NEXLARA_RISK_STATE':str(Path(d,'risk.json'))}):
            self.assertTrue(news_catalysts.consume('AAPL',{'id':'story-1'}))
            self.assertFalse(news_catalysts.consume('AAPL',{'id':'story-1'}))
            Path(d,'risk.news.json').write_text('invalid')
            with self.assertRaises(ValueError):news_catalysts.consume('AAPL',{'id':'story-2'})

HAVE_ENGINE=importlib.util.find_spec('alpaca_trade_api') is not None
@unittest.skipUnless(HAVE_ENGINE,'Full engine dependencies required in candidate image')
class EngineWiringTests(unittest.TestCase):
    def test_short_rounds_down_to_whole_shares(self):
        import main as engine
        row={'atr':1,'ema9':99,'ema21':100,'ema55':101,'vwap':101,'Volume':200,'vol_ma':100,'Close':100}
        api=SimpleNamespace(get_asset=lambda s:SimpleNamespace(tradable=True,shortable=True,easy_to_borrow=True),get_account=lambda:SimpleNamespace(shorting_enabled=True,equity='5000'))
        risk=SimpleNamespace(calc_position_size=lambda p,**kw:(9.99,999),risk_per_trade=lambda *a:(1,.01))
        acct=SimpleNamespace(get_day_trade_count=lambda:0,get_buying_power=lambda:20000)
        orders=Mock();orders.submit_short.return_value=None
        with patch.multiple(engine,api=api,risk_mgr=risk,acct_mgr=acct,order_mgr=orders,_shorts_enabled=True,data_feed=SimpleNamespace(get_last_price=lambda s:100,get_latest_5m=lambda s:row)),patch.object(engine.explainer,'explain_entry'):
            engine._execute_short_entry('AAPL','EMA_VWAP_SHORT')
        self.assertEqual(orders.submit_short.call_args.kwargs['qty'],9)

    def test_new_strategy_and_news_use_reconciled_buy_lifecycle(self):
        import main as engine
        row={'atr':1,'ema9':99,'ema21':100,'ema55':101,'vwap':101,'Volume':200,'vol_ma':100,'Close':100}
        risk=SimpleNamespace(calc_position_size=lambda p,**kw:(2,200),risk_per_trade=lambda *a:(1,.01))
        acct=SimpleNamespace(get_day_trade_count=lambda:0,get_buying_power=lambda:20000)
        orders=Mock();orders.submit_buy.return_value=None
        for name in ['EMA_PULLBACK','DONCHIAN','NEWS_MOMENTUM']:
            with patch.multiple(engine,risk_mgr=risk,acct_mgr=acct,order_mgr=orders,data_feed=SimpleNamespace(get_last_price=lambda s:100,get_latest_5m=lambda s:row)),patch.object(engine.explainer,'explain_entry'):
                engine._execute_entry('AAPL',name)
            self.assertEqual(orders.submit_buy.call_args.kwargs['strategy'],name)

    def test_new_intraday_strategies_close_at_time_stop(self):
        import main as engine
        positions={str(i):SimpleNamespace(strategy=s) for i,s in enumerate(['EMA_PULLBACK','DONCHIAN','NEWS_MOMENTUM'])}
        with patch.multiple(engine,api=SimpleNamespace(get_clock=lambda:SimpleNamespace(is_open=True)),risk_mgr=SimpleNamespace(positions=positions),log=Mock()),patch.object(engine,'_execute_exit') as close:
            engine.time_stop_close()
        self.assertEqual(close.call_count,3)
