"""Margin allocation tests with synthetic broker state; no external orders."""
import os
import sys
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from allocation import allocation_capacity,allocation_budget
from risk_manager import RiskManager
import config

class AllocationTests(unittest.TestCase):
    def setUp(self):
        self.account={'equity':'5000','buying_power':'20000','regt_buying_power':'10000','multiplier':'4'}
    def state(self,strategy='EMA_VWAP',positions=None,orders=None,slots=20):
        return allocation_capacity(self.account,positions or [],orders or [],strategy,slots,4,5)
    def test_first_order_spreads_intraday_buying_power(self):
        state=self.state()
        self.assertEqual(state['capacity'],19000)
        self.assertEqual(allocation_budget(state,1000),950)
    def test_swing_uses_overnight_capacity(self):
        self.assertEqual(allocation_budget(self.state('TREND_SWING'),1000),475)
        self.account['regt_buying_power']='1000'
        self.assertEqual(self.state('RSI_FADE')['capacity'],950)
    def test_no_overnight_field_never_assumes_intraday_power(self):
        del self.account['regt_buying_power']
        with self.assertRaises(ValueError):self.state('TREND_SWING')
        self.assertEqual(self.state()['capacity'],19000)
    def test_exposure_includes_longs_and_shorts_gross(self):
        positions=[dict(symbol='A',side='long',qty='10',market_value='8000'),dict(symbol='B',side='short',qty='-10',market_value='-9000')]
        self.assertEqual(self.state(positions=positions)['capacity'],2000)
        self.assertEqual(self.state('TREND_SWING',positions=positions)['capacity'],0)
    def test_pending_entries_take_slots_and_capacity_but_protective_stops_do_not(self):
        positions=[dict(symbol='A',side='long',qty='10',market_value='1000')]
        orders=[dict(symbol='A',side='sell',qty='10',filled_qty='0',stop_price='95'),dict(symbol='B',side='buy',qty='10',filled_qty='2',limit_price='100')]
        state=self.state(positions=positions,orders=orders)
        self.assertEqual(state['slots'],18);self.assertEqual(state['exposure'],1800)
    def test_unknown_pending_value_blocks_allocation(self):
        with self.assertRaises(ValueError):self.state(orders=[dict(symbol='A',side='buy',qty='10',filled_qty='0')])
    def test_full_slots_and_hard_order_cap(self):
        self.assertEqual(allocation_budget(self.state(slots=1),1000),1000)
        positions=[dict(symbol='A',side='long',qty='10',market_value='1000')]
        self.assertEqual(allocation_budget(self.state(positions=positions,slots=1),1000),0)
    def test_risk_sizing_and_submission_recheck_same_capacity(self):
        positions=[];orders=[]
        acct=SimpleNamespace(api=SimpleNamespace(list_orders=lambda **_:orders),get_account=lambda:SimpleNamespace(**self.account),
            get_open_positions=lambda:positions,get_portfolio_value=lambda:5000,get_buying_power=lambda:float(self.account['buying_power']),get_position_count=lambda:len(positions))
        risk=RiskManager(acct)
        with patch.multiple(config,ALLOCATION_MODE='fill_slots',MAX_CONCURRENT_POSITIONS=20,MAX_ORDER_VALUE=1000,HALT_THRESHOLD_VALUE=4500,MAX_GROSS_EXPOSURE=4,BUYING_POWER_RESERVE_PCT=5):
            qty,value=risk.calc_position_size(100,strategy='EMA_VWAP')
            self.assertLessEqual(qty*100.05,950)
            self.assertGreater(value,949)
            self.assertTrue(risk.validate_order('A',100.05,qty,strategy='EMA_VWAP')[0])
            self.account['buying_power']='1'
            self.assertFalse(risk.validate_order('A',100.05,qty,strategy='EMA_VWAP')[0])
    def test_margin_outage_denies_sizing_without_fallback(self):
        acct=SimpleNamespace(get_portfolio_value=lambda:5000,get_buying_power=lambda:20000,get_account=lambda:None)
        with patch.object(config,'ALLOCATION_MODE','fill_slots'):
            self.assertEqual(RiskManager(acct).calc_position_size(100,'EMA_VWAP'),(0,0))

try:
    from cryptography.fernet import Fernet
    CRYPTO=True
except ImportError:CRYPTO=False

@unittest.skipUnless(CRYPTO,'cryptography required')
class AllocationSettingsTests(unittest.TestCase):
    def test_migration_preserves_keys_ai_and_risk_baseline(self):
        from backend.settings_store import SettingsStore
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(directory)
            values=store.read();values.update(schema_version=3,max_positions=3,starting_capital=5000,halt_equity=4500,api_key='test',secret_key='test-secret',ai_api_key='ai-test',ai_enabled=True)
            store.write(values)
            migrated=store.read()
            self.assertEqual(migrated['max_positions'],20)
            self.assertEqual(migrated['allocation_mode'],'fill_slots')
            self.assertEqual(migrated['starting_capital'],5000);self.assertEqual(migrated['halt_equity'],4500)
            self.assertEqual(migrated['secret_key'],'test-secret');self.assertTrue(migrated['ai_enabled'])
    def test_new_saved_position_limit_is_not_reset_again(self):
        from backend.settings_store import SettingsStore
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(directory);values=store.read();values.update(max_positions=12);store.write(values)
            self.assertEqual(store.read()['max_positions'],12)
