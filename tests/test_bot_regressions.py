"""Offline regression tests. Broker objects are fakes; no orders reach a network."""
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
# In the container, source is mounted at /app and tests at /tests.
sys.path.insert(0, '/app')
import config
from bot_runtime import BotRuntime, InstanceLock
from risk_manager import RiskManager, LivePosition
from order_manager import OrderManager
def setUpModule():
    directory=tempfile.TemporaryDirectory()
    env=patch.dict(os.environ,{'NEXLARA_RESEARCH_DB':str(Path(directory.name,'research.sqlite3'))})
    env.start()
    unittest.addModuleCleanup(directory.cleanup)
    unittest.addModuleCleanup(env.stop)

import strategy_selector as selector
import strategy_ema_vwap as ema
import strategy_ema_vwap_short as short
import strategy_orb as orb
import strategy_rsi as rsi
import strategy_rsi_fade as fade


def account():
    return SimpleNamespace(get_portfolio_value=lambda: 100.,
                           get_buying_power=lambda: 100.,
                           get_position_count=lambda: 0)


def position(side='long', qty=1):
    return LivePosition('XYZ', side, 100, qty, '2026-10-23 10:00:00',
                        'EMA_VWAP', 95, 110, high_water=100)


class RiskTests(unittest.TestCase):
    def setUp(self):
        self.risk = RiskManager(account())
        self.risk.init_daily(100)

    def test_repeat_daily_init_preserves_loss_baseline(self):
        self.risk.init_daily(99)
        self.assertEqual(self.risk._daily_start_value, 100)

    def test_invalid_orders_rejected(self):
        for price, qty in ((0, 1), (-1, 1), (float('nan'), 1), (1, float('inf')), (1, -1)):
            self.assertFalse(self.risk.validate_order('XYZ', price, qty)[0])

    def test_halt_applies_to_validation(self):
        self.risk._bot_halted = True
        self.assertFalse(self.risk.validate_order('XYZ', 1, 1)[0])

    def test_size_respects_budget_for_expensive_stock(self):
        qty, value = self.risk.calc_position_size(1000)
        self.assertGreater(qty, 0)
        self.assertLessEqual(value, 5)
        self.assertLessEqual(qty * round(1000 * (1 + config.LIMIT_OFFSET_PCT), 2), 5)

    def test_zero_price_size(self):
        self.assertEqual(self.risk.calc_position_size(0), (0, 0))

    def test_short_profit_sign(self):
        self.risk.record_entry(position('short'))
        trade = self.risk.record_exit('XYZ', 90, 'target')
        self.assertGreater(trade.pnl, 0)
        self.assertEqual(trade.pnl_pct, 10)

    def test_short_loss_sign(self):
        self.risk.record_entry(position('short'))
        self.assertLess(self.risk.record_exit('XYZ', 110, 'stop').pnl, 0)

    def test_partial_exit_preserves_remaining_position(self):
        self.risk.record_entry(position(qty=2))
        trade = self.risk.record_exit('XYZ', 110, 'partial', .5)
        self.assertEqual(trade.qty, .5)
        self.assertEqual(self.risk.positions['XYZ'].qty, 1.5)

    def test_short_water_mark_moves_down(self):
        self.risk.record_entry(position('short'))
        self.risk.update_high_water('XYZ', 90)
        self.risk.update_high_water('XYZ', 95)
        self.assertEqual(self.risk.positions['XYZ'].high_water, 90)

    def test_broker_outage_blocks_entries(self):
        self.risk.acct.get_position_count = Mock(side_effect=RuntimeError('offline'))
        self.assertFalse(self.risk.can_trade()[0])


class StrategyTests(unittest.TestCase):
    def test_selection_applies_under_pdt(self):
        with patch.dict(os.environ, {'STRATEGY': 'orb'}), patch.object(selector, 'load_disabled', return_value=set()):
            self.assertEqual(selector.get_applicable_strategies('XYZ', {}, can_day_trade=False), [])

    def test_disabled_applies_under_pdt(self):
        with patch.dict(os.environ, {'STRATEGY': ''}), patch.object(selector, 'load_disabled', return_value={'RSI_BOUNCE'}):
            self.assertEqual(selector.get_applicable_strategies('XYZ', {}, can_day_trade=False), [])

    def test_frontend_rsi_alias(self):
        with patch.dict(os.environ, {'STRATEGY': 'rsi'}), patch.object(selector, 'load_disabled', return_value=set()):
            self.assertEqual(selector.get_applicable_strategies('XYZ', {}, can_day_trade=False)[0][0], 'RSI_BOUNCE')

    def test_unknown_strategy_rejected(self):
        with patch.dict(os.environ, {'STRATEGY': 'custom'}):
            with self.assertRaises(ValueError): selector.filter_enabled([])

    def test_all_five_strategy_signals(self):
        self.assertEqual(ema.check_signal(dict(ema9=101, ema21=100, ema55=99,
                         vwap=100, Close=101, Volume=200, vol_ma=100, ema_cross_up=True)), 'BUY')
        self.assertEqual(short.check_signal(dict(ema9=99, ema21=100, ema55=101,
                         vwap=100, Close=99, Volume=200, vol_ma=100, ema_cross_down=True)), 'SHORT')
        self.assertEqual(orb.check_signal(dict(Close=101, Volume=200, vol_ma=100),
                                          dict(high=100, low=99)), 'BUY')
        self.assertEqual(rsi.check_signal(dict(rsi7=20, Close=100, bb_lower=100, sma50=99)), 'BUY')
        self.assertEqual(fade.check_signal(dict(rsi7=80, Close=100, bb_upper=100, sma50=101)), 'SHORT')

    def test_missing_data_never_trades(self):
        for module in (ema, short, rsi, fade):
            self.assertEqual(module.check_signal(None), 'NONE')
        self.assertEqual(orb.check_signal(None, None), 'NONE')

    def test_nan_does_not_trigger_momentum(self):
        row = dict(ema9=101, ema21=100, ema55=99, vwap=100, Close=101,
                   Volume=200, vol_ma=float('nan'), ema_cross_up=True)
        self.assertEqual(ema.check_signal(row), 'NONE')

    def test_orb_requires_valid_volume(self):
        self.assertEqual(orb.check_signal(dict(Close=101, Volume=200, vol_ma=math.nan),
                                          dict(high=100, low=99)), 'NONE')

    def test_activated_long_trailing_stop_stays_active(self):
        pos = position(); pos.trail_activate=102; pos.high_water=105
        self.assertEqual(ema.check_exit(pos, dict(Close=101, atr=1)), (True, 'trailing_stop'))

    def test_activated_short_trailing_stop_stays_active(self):
        pos = position('short'); pos.stop_loss=110; pos.take_profit=80
        pos.trail_activate=98; pos.high_water=95
        self.assertEqual(short.check_exit(pos, dict(Close=99, atr=1)), (True, 'trailing_stop'))


class OrderTests(unittest.TestCase):
    def setUp(self):
        self.api = Mock()
        self.risk = RiskManager(account())
        self.manager = OrderManager(self.api, self.risk, account())

    def test_partial_fill_survives_cancellation(self):
        partial = SimpleNamespace(status='partially_filled', filled_qty='0.25', filled_avg_price='100')
        canceled = SimpleNamespace(status='canceled', filled_qty='0.25', filled_avg_price='100')
        self.api.get_order.side_effect = [partial, canceled]
        with patch.object(config, 'ORDER_POLL_TIMEOUT', 1), patch('order_manager.time.sleep'):
            result = self.manager._poll_fill('id', 'XYZ')
        self.assertTrue(result['filled'])
        self.assertEqual(result['filled_qty'], .25)
        self.api.cancel_order.assert_called_once_with('id')

    def test_fill_races_cancellation(self):
        self.api.get_order.return_value = SimpleNamespace(status='filled', filled_qty='1', filled_avg_price='100')
        with patch.object(config, 'ORDER_POLL_TIMEOUT', 0):
            self.assertEqual(self.manager._poll_fill('id', 'XYZ')['filled_qty'], 1)

    def test_ambiguous_entry_not_retried(self):
        self.api.submit_order.side_effect = TimeoutError()
        with patch('order_manager.time.sleep'):
            self.assertIsNone(self.manager.submit_buy('XYZ', 1, 1, 'EMA_VWAP', .9))
        self.assertEqual(self.api.submit_order.call_count, 1)
        self.assertTrue(self.risk.is_halted())

    def test_short_obeys_order_cap(self):
        self.assertIsNone(self.manager.submit_short('XYZ', 1, 100, 'EMA_VWAP_SHORT', 110))
        self.api.submit_order.assert_not_called()

    def test_unresolved_cancel_halts(self):
        self.api.get_order.return_value = SimpleNamespace(status='new', filled_qty='0')
        with patch.object(config, 'ORDER_POLL_TIMEOUT', 0), patch('order_manager.time.sleep'):
            with self.assertRaises(RuntimeError): self.manager._poll_fill('id', 'XYZ')
        self.assertTrue(self.risk.is_halted())

    def test_failed_stop_cancel_blocks_exit(self):
        self.manager.stop_orders['XYZ'] = 'stop'
        self.api.cancel_order.side_effect = TimeoutError()
        self.assertFalse(self.manager.submit_sell('XYZ', 1, 100, 'stop')['filled'])
        self.api.submit_order.assert_not_called()


class RuntimeTests(unittest.TestCase):
    def test_lock_is_exclusive_and_reusable(self):
        with tempfile.TemporaryDirectory() as directory:
            lock = InstanceLock(Path(directory)/'lock')
            try:
                with self.assertRaises(RuntimeError): InstanceLock(Path(directory)/'lock')
            finally: lock.close()
            InstanceLock(Path(directory)/'lock').close()

    def test_output_drained_without_dashboard(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'dummy.py'
            script.write_text("for i in range(20000): print('x'*100)\n")
            runtime = BotRuntime(Path(directory)/'logs')
            process = runtime.start('ema_vwap', script, dict(os.environ))
            self.assertEqual(process.wait(timeout=15), 0)
            runtime.readers['ema_vwap'].join(timeout=5)
            self.assertEqual(len(runtime.logs['ema_vwap']), 200)
            self.assertGreater((Path(directory)/'logs/bot-process.log').stat().st_size, 100_000)
            runtime.stop()

    def test_only_one_engine_and_unknown_stop_is_safe(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory)/'dummy.py'; script.write_text('import time; time.sleep(30)')
            runtime = BotRuntime(Path(directory)/'logs')
            try:
                runtime.start('ema_vwap', script, dict(os.environ))
                with self.assertRaises(RuntimeError): runtime.start('orb', script, dict(os.environ))
                with self.assertRaises(KeyError): runtime.stop('missing')
                self.assertTrue(runtime.alive('ema_vwap'))
            finally: runtime.stop()

class DurableRiskTests(unittest.TestCase):
    def test_paper_position_can_use_larger_cap_without_exceeding_it(self):
        account = SimpleNamespace(get_portfolio_value=lambda:5000, get_buying_power=lambda:20000)
        with patch.object(config, 'MAX_ORDER_VALUE', 250), patch.object(config, 'MAX_POSITION_PCT', .05):
            quantity, amount = RiskManager(account).calc_position_size(100)
        self.assertGreater(amount, 249)
        self.assertLessEqual(quantity * round(100 * (1 + config.LIMIT_OFFSET_PCT), 2), 250)

    def test_restart_retains_original_daily_baseline_and_halt(self):
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from risk_manager import RiskManager
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'NEXLARA_RISK_STATE':str(Path(directory,'risk.json'))}):
            account = SimpleNamespace(get_portfolio_value=lambda:97, get_position_count=lambda:0)
            first = RiskManager(account)
            first.init_daily(100)
            self.assertFalse(first.can_trade()[0])
            second = RiskManager(account)
            second.init_daily(97)
            self.assertEqual(second._daily_start_value,100)
            self.assertTrue(second._daily_halted)
            self.assertFalse(second.can_trade()[0])

    def test_corrupt_checkpoint_blocks_initialization(self):
        import tempfile
        from unittest.mock import patch
        from pathlib import Path
        from risk_manager import RiskManager
        with tempfile.TemporaryDirectory() as directory, patch.dict(os.environ, {'NEXLARA_RISK_STATE':str(Path(directory,'risk.json'))}):
            Path(directory,'risk.json').write_text('invalid')
            with self.assertRaises(RuntimeError):
                RiskManager(None).init_daily(100)


if __name__ == '__main__':
    unittest.main()
