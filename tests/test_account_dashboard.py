"""Read-only account dashboard endpoints with mocked broker responses."""
import asyncio
import json
from datetime import datetime, timezone
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fastapi import HTTPException
from backend import managed


class AccountDashboardTests(unittest.TestCase):
    def setUp(self):
        values=dict(api_key='PRIVATE-BROKER-KEY',secret_key='PRIVATE-BROKER-SECRET',paper_account_id='paper-account')
        self.settings=patch.object(managed,'store',Mock(read=Mock(return_value=values)))
        self.settings.start();self.addCleanup(self.settings.stop)

    def test_snapshot_reads_current_account_positions_and_recent_orders(self):
        calls=[]
        async def broker(path,values,data=False,params=None):
            calls.append((path,params))
            if path=='/v2/account':return dict(id='paper-account',equity='5100',cash='3000',buying_power='12000',last_equity='5000',secret_key='PRIVATE-BROKER-SECRET')
            if path=='/v2/positions':return [dict(symbol='META',qty='2',market_value='2100',unrealized_pl='100',private='discard')]
            if path=='/v2/orders':return [dict(id='order',symbol='META',status='filled',filled_qty='2',filled_avg_price='1050',private='discard')]
            if path=='/v2/clock':return dict(is_open=True,timestamp='2026-10-26T14:00:00Z',next_close='2026-10-26T20:00:00Z')
            raise AssertionError(path)
        with patch.object(managed,'broker',side_effect=broker):result=asyncio.run(managed.account_snapshot())
        self.assertEqual(result['account']['equity'],'5100')
        self.assertEqual(result['positions'][0]['symbol'],'META')
        self.assertEqual(result['orders'][0]['status'],'filled')
        self.assertEqual(result['account_id'],'paper-account')
        self.assertEqual(dict(calls)['/v2/orders'],dict(status='all',limit=50,direction='desc',nested='false'))
        for value in ['PRIVATE-BROKER-KEY','PRIVATE-BROKER-SECRET','private']:
            self.assertNotIn(value,json.dumps(result))
        self.assertEqual(len(calls),4)

    def test_snapshot_failure_does_not_return_a_false_empty_account(self):
        async def broker(path,*args,**kwargs):
            if path=='/v2/account':raise HTTPException(502,'Broker unavailable')
            return []
        with patch.object(managed,'broker',side_effect=broker),self.assertRaises(HTTPException):
            asyncio.run(managed.account_snapshot())

    def test_snapshot_rejects_changed_account_identity(self):
        async def broker(path,*args,**kwargs):
            if path=='/v2/account':return dict(id='different-account')
            if path=='/v2/clock':return {}
            return []
        with patch.object(managed,'broker',side_effect=broker),self.assertRaises(HTTPException) as caught:
            asyncio.run(managed.account_snapshot())
        self.assertEqual(caught.exception.status_code,409)

    def test_history_normalizes_values_without_fabricating_missing_observations(self):
        now=int(datetime.now(timezone.utc).timestamp())
        payload=dict(timestamp=[now-30,now-60,now-30,now-20,now-10,now-5,now+100,None],
                     equity=[5000,0,5010,None,'NaN',-10,9999,100])
        async def broker(path,values,data=False,params=None):
            self.assertEqual(path,'/v2/account/portfolio/history')
            self.assertEqual(params['period'],'1D');self.assertEqual(params['timeframe'],'5Min')
            self.assertEqual(params['intraday_reporting'],'continuous')
            return payload
        with patch.object(managed,'broker',side_effect=broker):result=asyncio.run(managed.equity_history('1D'))
        self.assertEqual([p['equity'] for p in result['points']],[0.,5010.,-10.])
        self.assertEqual(result['account_id'],'paper-account')
        self.assertNotIn('PRIVATE',json.dumps(result))

    def test_history_ranges_use_valid_broker_timeframes(self):
        calls=[]
        async def broker(path,values,data=False,params=None):
            calls.append(params);return dict(timestamp=[],equity=[])
        with patch.object(managed,'broker',side_effect=broker):
            for period in ['1D','1W','1M','3M','1Y']:
                self.assertEqual(asyncio.run(managed.equity_history(period))['points'],[])
        self.assertEqual([(p['period'],p['timeframe']) for p in calls],[('1D','5Min'),('1W','1H'),('1M','1D'),('3M','1D'),('1A','1D')])
        self.assertNotIn('intraday_reporting',calls[-1])

    def test_history_invalid_period_and_mismatched_arrays_are_rejected(self):
        with self.assertRaises(HTTPException) as invalid:asyncio.run(managed.equity_history('wrong'))
        self.assertEqual(invalid.exception.status_code,422)
        async def broker(*args,**kwargs):return dict(timestamp=[1,2],equity=[100])
        with patch.object(managed,'broker',side_effect=broker),self.assertRaises(HTTPException) as incomplete:
            asyncio.run(managed.equity_history('1M'))
        self.assertEqual(incomplete.exception.status_code,502)


if __name__=='__main__':unittest.main()
