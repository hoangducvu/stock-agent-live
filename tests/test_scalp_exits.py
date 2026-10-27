import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import unittest
from datetime import datetime,timedelta
from zoneinfo import ZoneInfo
from types import SimpleNamespace
from unittest.mock import patch,Mock
import scalp_exits as exits

class ScalpExitTests(unittest.TestCase):
    def setUp(self):
        self.now=datetime(2026,10,26,11,0,tzinfo=ZoneInfo('America/New_York'))
    def position(self,side='long',strategy='EMA_VWAP'):
        sl,tp,trigger=exits.calc_stops(100,1,side)
        return SimpleNamespace(strategy=strategy,side=side,entry_price=100,stop_loss=sl,take_profit=tp,
            trail_activate=trigger,high_water=100,entry_time=(self.now-timedelta(minutes=10)).isoformat())
    def test_time_limit_applies_to_all_intraday_even_without_data(self):
        for strategy in exits.INTRADAY:
            pos=self.position(strategy=strategy);pos.entry_time=(self.now-timedelta(minutes=30)).isoformat()
            self.assertEqual(exits.check_exit(pos,None,self.now),(True,'scalp_max_hold'))
    def test_swing_and_external_never_use_scalp_exit(self):
        for strategy in ['TREND_SWING','RSI_BOUNCE','RSI_FADE','EXTERNAL']:
            pos=self.position(strategy=strategy);pos.entry_time='2026-10-25 09:30:00'
            self.assertEqual(exits.check_exit(pos,{'Close':1},self.now),(False,''))
    def test_hold_limit_respects_new_york_naive_timestamp(self):
        pos=self.position();pos.entry_time='2026-10-26 10:31:00'
        self.assertFalse(exits.check_exit(pos,None,self.now)[0])
        self.assertTrue(exits.check_exit(pos,None,self.now+timedelta(minutes=1))[0])
    def test_stop_independent_of_missing_atr(self):
        for side,price in [('long',98),('short',102)]:
            self.assertEqual(exits.check_exit(self.position(side),{'Close':price},self.now),(True,'scalp_stop'))
    def test_momentum_reversal_both_directions(self):
        for side,fast,slow in [('long',99,100),('short',101,100)]:
            self.assertEqual(exits.check_exit(self.position(side),{'Close':100,'ema9':fast,'ema21':slow},self.now),(True,'scalp_momentum_reversal'))
    def test_trailing_ratchets_and_does_not_take_fixed_profit(self):
        for side,peak,pullback in [('long',103,102),('short',97,98)]:
            pos=self.position(side)
            self.assertFalse(exits.check_exit(pos,{'Close':peak,'atr':1},self.now)[0])
            tightened=pos.stop_loss
            self.assertFalse(exits.check_exit(pos,{'Close':peak,'atr':4},self.now)[0])
            self.assertEqual(pos.stop_loss,tightened)
            self.assertTrue(exits.check_exit(pos,{'Close':pullback,'atr':1},self.now)[0])
    def test_invalid_data_does_not_invent_exit_or_stop(self):
        pos=self.position();old=pos.stop_loss
        self.assertFalse(exits.check_exit(pos,{'Close':float('nan'),'atr':1},self.now)[0])
        self.assertEqual(pos.stop_loss,old)
    def test_initial_stops_no_fixed_target(self):
        self.assertEqual(exits.calc_stops(100,1),(98.5,None,101))
        self.assertEqual(exits.calc_stops(100,1,'short'),(101.5,None,99))

try:
    import fastapi,pandas,alpaca_trade_api,apscheduler
    FULL=True
except ImportError:FULL=False

@unittest.skipUnless(FULL,'Full engine dependencies required')
class ScalpWiringTests(unittest.TestCase):
    def test_engine_routes_all_intraday_exits_and_preserves_external(self):
        import main
        now=datetime(2026,10,26,11,0,tzinfo=ZoneInfo('America/New_York'))
        positions={s:SimpleNamespace(strategy=s,side='short' if s=='EMA_VWAP_SHORT' else 'long',entry_time='2026-10-26 10:00:00') for s in exits.INTRADAY}
        positions['EXTERNAL']=SimpleNamespace(strategy='EXTERNAL')
        with patch.multiple(main,risk_mgr=SimpleNamespace(positions=positions),data_feed=SimpleNamespace(get_latest_5m=lambda _:None)),patch.object(main,'now_et',return_value=now),patch.object(main,'_execute_exit') as sell,patch.object(main,'_execute_cover') as cover:
            main._check_exits()
        self.assertEqual(sell.call_count,5);self.assertEqual(cover.call_count,1)
