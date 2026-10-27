"""Full-dependency tests, executed in the API image with networking disabled."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
import time
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, '/app')
HAVE_DEPS = all(importlib.util.find_spec(name) is not None for name in ('fastapi', 'pandas', 'alpaca_trade_api', 'cryptography'))
if os.environ.get('NEXLARA_REQUIRE_TEST_DEPS') == '1' and not HAVE_DEPS:
    raise RuntimeError('Full application dependencies are required for container validation')


@unittest.skipUnless(HAVE_DEPS, 'Run inside the API image for full-dependency checks')
class ApplicationTests(unittest.TestCase):
    def test_health_and_strategy_routes(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        with TestClient(app) as client:
            self.assertEqual(client.get('/api/health').json()['bot_running'], False)
            self.assertEqual(len(client.get('/api/strategies').json()), 4)

    def test_invalid_strategy_rejected_without_launch(self):
        from fastapi.testclient import TestClient
        from backend import main as backend
        with TestClient(backend.app) as client, patch.object(backend.runtime, 'start') as start:
            response = client.post('/api/bot/start', json=dict(api_key='fake', secret_key='fake', strategy='custom'))
            self.assertEqual(response.status_code, 410)
            start.assert_not_called()

    def test_test_order_needs_explicit_credentials(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/bot/test-order', json={'symbol': 'XYZ'}).status_code, 410)

    def test_untrusted_origin_cannot_stop_bots(self):
        from fastapi.testclient import TestClient
        from backend.main import app
        with TestClient(app) as client:
            self.assertEqual(client.post('/api/bot/stop', headers={'Origin': 'https://untrusted.example'}).status_code, 403)

    def test_early_process_exit_is_not_reported_as_started(self):
        from fastapi.testclient import TestClient
        from backend import main as backend
        exited = SimpleNamespace(poll=lambda: 1, pid=99999)
        with TestClient(backend.app) as client, patch.object(backend.runtime, 'start', return_value=exited):
            from fastapi import HTTPException
            with self.assertRaises(HTTPException) as error:
                asyncio.run(backend.bot_start(backend.BotStartRequest(api_key='fake', secret_key='fake', strategy='ema_vwap')))
            self.assertEqual(error.exception.status_code, 502)

    def test_requested_paper_mode_overrides_inherited_live_mode(self):
        from fastapi.testclient import TestClient
        from backend import main as backend
        exited = SimpleNamespace(poll=lambda: 1, pid=99999)
        with TestClient(backend.app) as client, patch.object(backend.runtime, 'start', return_value=exited) as start:
            with patch.dict(os.environ, {'TRADING_MODE': 'live', 'APCA_API_KEY_ID': 'old'}):
                from fastapi import HTTPException
                with self.assertRaises(HTTPException):
                    asyncio.run(backend.bot_start(backend.BotStartRequest(api_key='fake', secret_key='fake', paper=True)))
            env = start.call_args.args[2]
            self.assertEqual(env['TRADING_MODE'], 'paper')
            self.assertEqual(env['APCA_API_KEY_ID'], 'fake')

    def test_import_engine_without_starting(self):
        import main
        self.assertIsNone(main.api)
        self.assertIsNone(main.scheduler)

    def test_rsi_handles_unbroken_trends(self):
        import pandas as pd
        import indicators
        self.assertEqual(indicators.rsi(pd.Series(range(40))).iloc[-1], 100)
        self.assertEqual(indicators.rsi(pd.Series(range(40, 0, -1))).iloc[-1], 0)
        self.assertEqual(indicators.rsi(pd.Series([100.]*40)).iloc[-1], 50)

    def test_fetch_timeout_does_not_wait_for_stuck_worker(self):
        from data_feed import DataFeed
        from unittest.mock import patch
        release = threading.Event()
        api = SimpleNamespace(get_bars=lambda *args, **kwargs: release.wait(5))
        feed = DataFeed(api)
        try:
            with patch('data_feed._API_TIMEOUT', .02):
                started = time.monotonic()
                self.assertEqual(feed._fetch_bars('XYZ', '5Min'), [])
                self.assertLess(time.monotonic() - started, 1)
                self.assertEqual(feed._fetch_bars('XYZ', '5Min'), [])
        finally:
            release.set()
