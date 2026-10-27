"""Larger allocations and restart-independent broker closing reports."""
import asyncio
from datetime import datetime, timedelta
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import config
from risk_manager import RiskManager
from daily_summary import closing_report, ET

class SizingTests(unittest.TestCase):
    def setUp(self):
        self.account=dict(equity='5000',buying_power='20000',regt_buying_power='10000',multiplier='4')
        self.acct=SimpleNamespace(get_portfolio_value=lambda:5000,get_buying_power=lambda:float(self.account['buying_power']),
            get_account=lambda:self.account,get_open_positions=lambda:[],api=SimpleNamespace(list_orders=lambda **_:[]))
        self.settings=patch.multiple(config,ALLOCATION_MODE='fill_slots',MAX_ORDER_VALUE=10000,
            MAX_CONCURRENT_POSITIONS=20,POSITION_SIZE_MULTIPLIER=10,MAX_GROSS_EXPOSURE=4,BUYING_POWER_RESERVE_PCT=5)
        self.settings.start();self.addCleanup(self.settings.stop)
    def test_tenfold_initial_scalp_preserves_limit_offset(self):
        qty,value=RiskManager(self.acct).calc_position_size(100,'EMA_VWAP')
        self.assertGreater(value,9495);self.assertLessEqual(qty*100.05,9500)
    def test_cap_and_overnight_capacity(self):
        with patch.object(config,'POSITION_SIZE_MULTIPLIER',20):
            self.assertLessEqual(RiskManager(self.acct).calc_position_size(100,'EMA_VWAP')[0]*100.05,10000)
        self.account['regt_buying_power']='1000'
        self.assertLessEqual(RiskManager(self.acct).calc_position_size(100,'TREND_SWING')[0]*100.05,950)
    def test_missing_broker_data_never_falls_back(self):
        self.acct.get_account=lambda:None
        self.assertEqual(RiskManager(self.acct).calc_position_size(100,'EMA_VWAP'),(0,0))
    def test_schema_upgrade_and_saved_choice(self):
        from backend.settings_store import SettingsStore
        with tempfile.TemporaryDirectory() as directory:
            store=SettingsStore(directory)
            values=store.read();values.update(schema_version=4,max_order_value=1000,api_key='test',secret_key='secret',max_positions=12,max_daily_loss_pct=1.5)
            store.write(values);migrated=store.read()
            self.assertEqual(migrated['position_size_multiplier'],10)
            self.assertEqual(migrated['max_order_value'],10000)
            self.assertEqual(migrated['max_positions'],12)
            self.assertEqual(migrated['secret_key'],'secret')
            self.assertEqual(migrated['max_daily_loss_pct'],1.5)
            migrated.update(position_size_multiplier=5,max_order_value=7500);store.write(migrated)
            self.assertEqual(store.read()['position_size_multiplier'],5)
            self.assertEqual(store.read()['max_order_value'],7500)

class SummaryTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.now=datetime(2026,11,27,13,6,tzinfo=ET) # early-close session
        self.close=self.now.replace(minute=0)
        self.values={'paper_account_id':'account-a'};self.calls=[]
        self.fills=[dict(id='fill-a',order_id='order-a',qty='10',price='100',side='buy',symbol='AAPL',transaction_time='2026-11-27T10:00:00-05:00'),
            dict(id='fill-b',order_id='order-a',qty='5',price='100',side='buy',symbol='AAPL',transaction_time='2026-11-27T10:01:00-05:00')]
        self.history=dict(timestamp=[(self.close-timedelta(minutes=5)).timestamp()],equity=[5050],profit_loss=[50])
    async def broker(self,path,values,params=None):
        self.calls.append((path,params))
        if path=='/v2/calendar':return [dict(date='2026-11-27',open='09:30',close='13:00')]
        if path=='/v2/account':return dict(id=values['paper_account_id'])
        if path=='/v2/account/portfolio/history':return self.history
        if path=='/v2/account/activities/FILL':return self.fills
        raise AssertionError(path)
    def run_report(self):return asyncio.run(closing_report(self.broker,self.values,self.temp.name,self.now))
    def test_early_close_persisted_summary_survives_engine_absence(self):
        report=self.run_report()['report']
        self.assertEqual(report['account_pnl'],50)
        self.assertEqual(report['fills'],2);self.assertEqual(report['filled_orders'],1)
        self.assertEqual(report['buy_volume'],1500)
        self.calls=[];self.assertEqual(self.run_report()['report'],report)
        self.assertEqual([p for p,_ in self.calls],['/v2/calendar'])
    def test_waits_until_close_plus_five_minutes(self):
        self.now=self.now.replace(minute=4)
        self.assertIsNone(self.run_report()['report'])
        self.assertEqual(len(self.calls),1)
    def test_zero_fills_still_saves_summary(self):
        self.fills=[];self.assertEqual(self.run_report()['report']['fills'],0)
        self.assertEqual(len(list(Path(self.temp.name).glob('*.json'))),1)
    def test_missing_close_data_is_retried_not_cached(self):
        self.history['timestamp']=[(self.close-timedelta(hours=1)).timestamp()]
        self.assertIsNone(self.run_report()['report'])
        self.assertFalse(list(Path(self.temp.name).glob('*.json')))
    def test_reports_are_account_scoped(self):
        self.run_report();self.values['paper_account_id']='account-b'
        self.assertEqual(self.run_report()['report']['account_id'],'account-b')
        self.assertEqual(len(list(Path(self.temp.name).glob('*.json'))),2)
    def test_account_mismatch_and_nonfinite_values_rejected(self):
        broker=self.broker
        async def mismatch(path,values,params=None):
            if path=='/v2/account':return {'id':'other'}
            return await broker(path,values,params=params)
        with self.assertRaises(ValueError):asyncio.run(closing_report(mismatch,self.values,self.temp.name,self.now))
        self.history['equity']=['NaN']
        with self.assertRaises(ValueError):self.run_report()
    def test_pagination_does_not_count_partial_fills_as_multiple_orders(self):
        broker=self.broker;first=[dict(self.fills[0],id=f'fill-{i}') for i in range(100)]
        async def paged(path,values,params=None):
            if path=='/v2/account/activities/FILL':return self.fills if params.get('page_token') else first
            return await broker(path,values,params=params)
        report=asyncio.run(closing_report(paged,self.values,self.temp.name,self.now))['report']
        self.assertEqual(report['fills'],102);self.assertEqual(report['filled_orders'],1)

class SummaryApiTests(unittest.TestCase):
    def test_dashboard_route_and_multiplier_validation(self):
        import httpx
        from backend import managed, main
        from backend.settings_store import SettingsStore
        async def check():
            with tempfile.TemporaryDirectory() as directory:
                store=SettingsStore(directory)
                with patch.object(managed,'store',store):
                    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=main.app),base_url='http://testserver') as client:
                        response=await client.get('/api/workspace/daily-summary')
                        self.assertEqual(response.status_code,200)
                        self.assertIsNone(response.json()['report'])
                        response=await client.put('/api/workspace/settings',json={'position_size_multiplier':0})
                        self.assertEqual(response.status_code,422)
                        response=await client.put('/api/workspace/settings',json={'position_size_multiplier':10,'max_order_value':10000})
                        self.assertEqual(response.status_code,200)
                        self.assertEqual(response.json()['position_size_multiplier'],10)
        asyncio.run(check())

if __name__=='__main__':unittest.main()
