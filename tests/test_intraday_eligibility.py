"""Current broker eligibility replaces retired local PDT limits."""
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from account_manager import AccountManager
import config

class IntradayEligibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.patch=patch.object(config,'DATA_DIR',self.temp.name);self.patch.start();self.addCleanup(self.patch.stop)
        self.env=patch.dict(os.environ,{'NEXLARA_ACCOUNT_SCOPE':'paper-one'});self.env.start();self.addCleanup(self.env.stop)
        self.account=SimpleNamespace(id='paper-one',status='ACTIVE',equity='100000',buying_power='200000',trading_blocked=False,account_blocked=False,trade_suspended_by_user=False)
        self.api=Mock();self.api.get_account.return_value=self.account
        self.manager=AccountManager(self.api)
    def test_repeated_round_trips_never_trigger_old_limit(self):
        for _ in range(5):self.manager.record_day_trade('AAPL')
        self.assertEqual(self.manager.get_day_trade_count(),5)
        self.assertTrue(self.manager.can_day_trade())
        self.account.equity='5000';self.account.buying_power='10000'
        self.assertTrue(self.manager.can_day_trade())
    def test_broker_blocks_and_invalid_balances_still_deny(self):
        for name,value in [('status','ACCOUNT_CLOSED'),('trading_blocked',True),('account_blocked',True),('trade_suspended_by_user',True),('buying_power','0'),('equity','NaN')]:
            original=getattr(self.account,name);setattr(self.account,name,value)
            self.assertFalse(self.manager.can_day_trade(),name)
            setattr(self.account,name,original)
        self.api.get_account.side_effect=TimeoutError()
        self.assertFalse(self.manager.can_day_trade())
    def test_history_survives_restart_and_does_not_cross_accounts(self):
        self.manager.record_day_trade('AAPL')
        self.assertEqual(AccountManager(self.api).get_day_trade_count(),1)
        with patch.dict(os.environ,{'NEXLARA_ACCOUNT_SCOPE':'paper-two'}):
            other=AccountManager(self.api)
            self.assertEqual(other.get_day_trade_count(),0)
        self.assertNotEqual(other._trade_history_path,self.manager._trade_history_path)
    def test_unscoped_legacy_file_is_not_assigned_to_new_account(self):
        Path(self.temp.name,'pdt_day_trades.json').write_text('[{"symbol":"AAPL","date":"2026-10-27"}]')
        self.assertEqual(AccountManager(self.api).get_day_trade_count(),0)

if __name__=='__main__':unittest.main()
