"""Startup never requires liquidation or invents ownership of existing orders."""
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock,patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'));sys.path.insert(0,'/app')
from broker_reconciliation import reconcile_broker_state
from risk_manager import RiskManager

class ExistingBrokerStateTests(unittest.TestCase):
    def test_existing_longs_shorts_and_orders_are_observed_without_mutation(self):
        api=Mock()
        api.list_positions.return_value=[SimpleNamespace(symbol='AMZN',qty='.04',avg_entry_price='228.73',side='long'),SimpleNamespace(symbol='XYZ',qty='-2',avg_entry_price='100',side='short')]
        api.list_orders.return_value=[SimpleNamespace(symbol='PFE')]
        risk=RiskManager(Mock());positions,orders=reconcile_broker_state(api,risk,Mock())
        self.assertEqual(risk.positions['AMZN'].strategy,'EXTERNAL')
        self.assertEqual(risk.positions['XYZ'].side,'short')
        self.assertEqual(risk.positions['XYZ'].qty,2)
        self.assertEqual(risk.positions['AMZN'].stop_loss,0)
        self.assertEqual(risk.pending_symbols,{'PFE'})
        api.submit_order.assert_not_called();api.close_position.assert_not_called();api.cancel_order.assert_not_called();api.cancel_all_orders.assert_not_called()
        self.assertEqual(len(positions),2)

    def test_pending_symbol_blocks_duplicate_entry(self):
        risk=RiskManager(Mock());risk.pending_symbols={'PFE'}
        allowed,reason=risk.validate_order('PFE',10,1)
        self.assertFalse(allowed);self.assertIn('pending',reason.lower())

    def test_pending_new_symbols_count_toward_position_limit(self):
        api=Mock();api.list_positions.return_value=[SimpleNamespace(symbol=s,qty=1,avg_entry_price=100,side='long') for s in ['AAPL','MSFT']]
        api.list_orders.return_value=[SimpleNamespace(symbol='NVDA')]
        account=SimpleNamespace(get_portfolio_value=lambda:5000,get_position_count=lambda:2)
        risk=RiskManager(account);reconcile_broker_state(api,risk,Mock())
        self.assertFalse(risk.can_trade()[0])

    def test_failed_order_reconciliation_cannot_assume_empty_orders(self):
        api=Mock();api.list_positions.return_value=[];api.list_orders.side_effect=TimeoutError()
        with self.assertRaises(TimeoutError):reconcile_broker_state(api,RiskManager(Mock()),Mock())
