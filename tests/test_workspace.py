"""Persistence, isolation and paper-only control regression tests."""
import asyncio
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
sys.path.insert(0, '/app')
CRYPTO = importlib.util.find_spec('cryptography') is not None
DEPS = CRYPTO and importlib.util.find_spec('fastapi') is not None

@unittest.skipUnless(CRYPTO, 'cryptography required in API image')
class SettingsTests(unittest.TestCase):
    def test_encrypted_keys_survive_reopen_and_are_not_returned(self):
        from backend.settings_store import SettingsStore
        with tempfile.TemporaryDirectory() as d:
            store = SettingsStore(d)
            values = {**store.read(), 'api_key':'paper-test-key', 'secret_key':'private-test-secret'}
            store.write(values)
            self.assertNotIn(b'private-test-secret', Path(d,'settings.sqlite3').read_bytes())
            reopened = SettingsStore(d)
            self.assertEqual(reopened.read()['secret_key'], 'private-test-secret')
            self.assertTrue(reopened.public()['credentials_saved'])
            self.assertNotIn('secret_key', reopened.public())
            self.assertNotIn('api_key', reopened.public())
            self.assertEqual(Path(d,'settings.key').stat().st_mode & 0o777, 0o600)

    def test_missing_key_does_not_silently_replace_saved_credentials(self):
        from backend.settings_store import SettingsStore
        with tempfile.TemporaryDirectory() as d:
            store = SettingsStore(d)
            store.read()
            store.write({'api_key':'key', 'secret_key':'secret'})
            Path(d,'settings.key').unlink()
            with self.assertRaises(Exception):
                store.read()

    def test_ai_key_is_encrypted_and_missing_key_forces_disabled(self):
        from backend.settings_store import SettingsStore
        with tempfile.TemporaryDirectory() as d:
            store=SettingsStore(d);values=store.read()
            values.update(ai_api_key='PRIVATE-AI-KEY',ai_enabled=True);store.write(values)
            self.assertTrue(store.public()['ai_enabled'])
            self.assertTrue(store.public()['ai_configured'])
            self.assertNotIn('ai_api_key',store.public())
            self.assertNotIn(b'PRIVATE-AI-KEY',Path(d,'settings.sqlite3').read_bytes())
            values.update(ai_api_key='',ai_enabled=True);store.write(values)
            self.assertFalse(store.read()['ai_enabled'])
            self.assertFalse(store.public()['ai_configured'])


@unittest.skipUnless(DEPS, 'FastAPI dependencies required in API image')
class WorkspaceTests(unittest.TestCase):
    def setUp(self):
        from fastapi.testclient import TestClient
        from backend import managed, main
        from backend.settings_store import SettingsStore
        self.temp = tempfile.TemporaryDirectory()
        self.store = SettingsStore(self.temp.name)
        self.patch = patch.object(managed, 'store', self.store)
        self.patch.start()
        self.client = TestClient(main.app)
        self.addCleanup(self.temp.cleanup)
        self.addCleanup(self.patch.stop)
        self.addCleanup(self.client.close)

    def configure(self):
        self.store.write({**self.store.read(),'api_key':'key','secret_key':'secret'})

    def fake_broker(self, positions=None, orders=None, equity='5000'):
        async def response(path, values, data=False, params=None):
            if path == '/v2/account': return {'id':'paper-account-1','status':'ACTIVE','equity':equity,'buying_power':'20000','shorting_enabled':True}
            if path == '/v2/clock': return {'is_open':False,'timestamp':'2026-10-25T15:00:00Z','next_open':'2026-10-26T09:30:00-04:00'}
            if path == '/v2/positions': return positions or []
            if path.startswith('/v2/orders'): return orders or []
            if path == '/v2/stocks/snapshots': return {'AAPL':{'dailyBar':{'c':100}}}
            if path == '/v1beta1/news': return {'news':[]}
            if path == '/v2/stocks/bars': return {'bars':{'AAPL':[{'c':100}]}}
            raise AssertionError(path)
        return response

    def test_legacy_trading_paths_cannot_bypass_preflight(self):
        for path in ['/api/bot/start','/api/bot/stop','/api/bot/test-order','/api/orders']:
            self.assertEqual(self.client.post(path,json={}).status_code,410)

    def test_live_headers_are_rejected(self):
        self.assertEqual(self.client.get('/api/account',headers={'X-Paper':'false'}).status_code,403)

    def test_cross_origin_settings_are_rejected(self):
        self.assertEqual(self.client.put('/api/workspace/settings',json={},headers={'Origin':'https://evil.example'}).status_code,403)

    def test_defaults_do_not_expose_keys(self):
        result=self.client.get('/api/workspace/settings').json()
        self.assertTrue(result['paper'])
        self.assertFalse(result['credentials_saved'])
        self.assertNotIn('secret_key', result)

    def test_one_key_and_invalid_halt_are_rejected(self):
        self.assertEqual(self.client.put('/api/workspace/settings',json={'api_key':'key'}).status_code,422)
        self.assertEqual(self.client.put('/api/workspace/settings',json={'halt_equity':5000}).status_code,422)

    def test_save_checks_broker_and_preserves_keys_on_later_edits(self):
        with patch('backend.managed.broker',side_effect=self.fake_broker()):
            result=self.client.put('/api/workspace/settings',json={'api_key':'key','secret_key':'secret'})
            self.assertEqual(result.status_code,200, result.text)
            self.assertNotIn('secret', result.text)
            result=self.client.put('/api/workspace/settings',json={'max_order_value':9})
            self.assertEqual(result.status_code,200,result.text)
        self.assertEqual(self.store.read()['api_key'],'key')
        self.assertEqual(self.store.read()['max_order_value'],9)

    def test_margin_slot_settings_validate_and_preserve_baseline(self):
        baseline=self.store.read()['starting_capital']
        result=self.client.put('/api/workspace/settings',json={'allocation_mode':'fill_slots','max_positions':30,'buying_power_reserve_pct':5,'max_gross_exposure_pct':400})
        self.assertEqual(result.status_code,200)
        self.assertEqual(result.json()['max_positions'],30)
        self.assertEqual(self.store.read()['starting_capital'],baseline)
        self.assertEqual(self.client.put('/api/workspace/settings',json={'max_positions':0}).status_code,422)
        self.assertEqual(self.client.put('/api/workspace/settings',json={'buying_power_reserve_pct':0}).status_code,422)
        self.assertEqual(self.client.put('/api/workspace/settings',json={'max_gross_exposure_pct':401}).status_code,422)

    def test_settings_cannot_change_while_running(self):
        from backend.main import runtime
        with patch.dict(runtime.processes, {'ema_vwap':object()}), patch.object(runtime,'alive',return_value=True):
            for body in ({}, {'max_order_value':500}, {'ai_enabled':False,'max_order_value':500}):
                self.assertEqual(self.client.put('/api/workspace/settings',json=body).status_code,409)

    def test_weekend_can_pass_and_no_orders_are_submitted(self):
        self.configure()
        with patch('backend.managed.broker',side_effect=self.fake_broker()):
            result=self.client.get('/api/workspace/readiness')
        self.assertEqual(result.status_code,200,result.text)
        self.assertTrue(result.json()['ready'],result.text)
        self.assertFalse(result.json()['clock']['is_open'])

    def test_existing_positions_and_orders_are_informational_at_start(self):
        self.configure()
        with patch('backend.managed.broker',side_effect=self.fake_broker(positions=[{'symbol':'AAPL'}],orders=[{'id':'order'}])):
            result=self.client.get('/api/workspace/readiness').json()
        self.assertTrue(result['ready'],result)
        informational=[c for c in result['checks'] if c['label'] in {'Broker positions','Pending orders'}]
        self.assertTrue(all(not c['blocking'] for c in informational))

    def test_no_credentials_blocks_start_without_launch(self):
        with patch('backend.main.runtime.start') as launch:
            result=self.client.post('/api/workspace/start')
        self.assertEqual(result.status_code,409,result.text)
        launch.assert_not_called()

    def test_start_uses_saved_paper_credentials_only(self):
        self.configure()
        with patch('backend.managed.broker',side_effect=self.fake_broker()), patch('backend.main.bot_start',new_callable=AsyncMock,return_value={'status':'starting'}) as launch:
            result=self.client.post('/api/workspace/start')
        self.assertEqual(result.status_code,200,result.text)
        req=launch.call_args.args[0]
        self.assertTrue(req.paper)
        self.assertEqual(req.api_key,'key')

    def test_data_outage_blocks_readiness(self):
        from fastapi import HTTPException
        self.configure()
        normal=self.fake_broker()
        async def broken(path,*args,**kwargs):
            if 'snapshots' in path: raise HTTPException(502,'Data unavailable')
            return await normal(path,*args,**kwargs)
        with patch('backend.managed.broker',side_effect=broken):
            self.assertFalse(self.client.get('/api/workspace/readiness').json()['ready'])

    def test_rotating_keys_preserves_nondefault_risk_and_selected_strategies(self):
        self.configure()
        values=self.store.read()
        values.update(paper_account_id='paper-account-1', max_daily_loss_pct=1.5, max_order_value=750, strategies=['orb'])
        self.store.write(values)
        with patch('backend.managed.broker',side_effect=self.fake_broker()):
            response=self.client.put('/api/workspace/settings',json={'api_key':'new-key','secret_key':'new-secret'})
        self.assertEqual(response.status_code,200,response.text)
        saved=self.store.read()
        self.assertEqual(saved['api_key'],'new-key')
        self.assertEqual(saved['max_daily_loss_pct'],1.5)
        self.assertEqual(saved['max_order_value'],750)
        self.assertEqual(saved['strategies'],['orb'])

    def test_rejected_new_keys_do_not_overwrite_saved_keys(self):
        from fastapi import HTTPException
        self.configure()
        with patch('backend.managed.broker',side_effect=HTTPException(409,'Paper account authentication failed')):
            response=self.client.put('/api/workspace/settings',json={'api_key':'bad-key','secret_key':'bad-secret'})
        self.assertEqual(response.status_code,409)
        self.assertEqual(self.store.read()['api_key'],'key')

    def test_switching_accounts_scales_equity_halt_to_new_account(self):
        self.configure()
        values=self.store.read();values['paper_account_id']='old-paper-account';self.store.write(values)
        with patch('backend.managed.broker',side_effect=self.fake_broker(equity='1000')):
            response=self.client.put('/api/workspace/settings',json={'api_key':'new-key','secret_key':'new-secret'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(self.store.read()['starting_capital'],1000)
        self.assertEqual(self.store.read()['halt_equity'],900)

    def test_empty_strategies_and_short_toggle_mismatch_rejected(self):
        self.assertEqual(self.client.put('/api/workspace/settings',json={'strategies':[]}).status_code,422)
        self.assertEqual(self.client.put('/api/workspace/settings',json={'strategies':['rsi_fade'],'shorts_enabled':False}).status_code,422)

    def test_validation_never_echoes_broker_secret(self):
        response=self.client.put('/api/workspace/settings',json={'secret_key':'SENSITIVE'*80})
        self.assertEqual(response.status_code,422)
        self.assertNotIn('SENSITIVE',response.text)

    def test_no_short_permission_blocks_readiness(self):
        self.configure()
        normal=self.fake_broker()
        async def no_shorts(path,*args,**kwargs):
            result=await normal(path,*args,**kwargs)
            if path=='/v2/account':result['shorting_enabled']=False
            return result
        with patch('backend.managed.broker',side_effect=no_shorts):
            result=self.client.get('/api/workspace/readiness').json()
        self.assertFalse(result['ready'])
        self.assertTrue(any(c['label']=='Short selling permission' and not c['ok'] for c in result['checks']))

    def test_slack_settings_encrypt_and_redact_webhook(self):
        webhook='https://hooks.slack.com/services/TEST/CHANNEL/SECRET'
        response=self.client.put('/api/workspace/settings',json={'slack_notifications':True,'slack_webhook':webhook,'slack_channel':'#paper-trades'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['slack_configured'])
        self.assertNotIn('SECRET',response.text)
        self.assertEqual(self.store.read()['slack_webhook'],webhook)
        self.assertNotIn(b'SECRET',Path(self.temp.name,'settings.sqlite3').read_bytes())
        self.assertNotIn('SECRET',self.client.get('/api/workspace/settings').text)

    def test_slack_rejects_non_slack_destination(self):
        self.assertEqual(self.client.put('/api/workspace/settings',json={'slack_notifications':True,'slack_webhook':'http://127.0.0.1/private'}).status_code,422)

    def test_research_status_does_not_return_provider_secret(self):
        with patch.dict(os.environ,{'ANTHROPIC_API_KEY':'PRIVATE-TEST-KEY','NEXLARA_RESEARCH_DB':str(Path(self.temp.name,'research.sqlite3'))}):
            response=self.client.get('/api/workspace/research')
        self.assertEqual(response.status_code,200,response.text)
        self.assertNotIn('PRIVATE-TEST-KEY',response.text)
        self.assertFalse(response.json()['enabled'])

    def test_ai_is_optional_encrypted_and_requires_explicit_opt_in(self):
        response=self.client.put('/api/workspace/settings',json={'ai_api_key':'PRIVATE-AI-KEY'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertTrue(response.json()['ai_configured'])
        self.assertFalse(response.json()['ai_enabled'])
        self.assertNotIn('PRIVATE-AI-KEY',response.text)
        self.assertNotIn('ai_api_key',response.json())
        response=self.client.put('/api/workspace/settings',json={'ai_enabled':True})
        self.assertTrue(response.json()['ai_enabled'])
        response=self.client.put('/api/workspace/settings',json={'ai_api_key':''})
        self.assertFalse(response.json()['ai_enabled'])
        self.assertFalse(response.json()['ai_configured'])

    def test_enabling_ai_with_empty_key_remains_disabled_even_with_env_key(self):
        with patch.dict(os.environ,{'AI_ENABLED':'true','ANTHROPIC_API_KEY':'ENV-KEY'}):
            response=self.client.put('/api/workspace/settings',json={'ai_enabled':True})
            self.assertEqual(response.status_code,200,response.text)
            self.assertFalse(response.json()['ai_enabled'])
            with patch.dict(os.environ,{'NEXLARA_RESEARCH_DB':str(Path(self.temp.name,'research.sqlite3'))}):
                status=self.client.get('/api/workspace/research').json()
                self.assertFalse(status['enabled']);self.assertFalse(status['credentials_configured'])

    def test_ai_key_can_be_removed_without_stopping_running_engine(self):
        from backend.main import runtime
        values=self.store.read();values.update(ai_api_key='PRIVATE-AI-KEY',ai_enabled=True);self.store.write(values)
        with patch.dict(runtime.processes,{'ema_vwap':object()}),patch.object(runtime,'alive',return_value=True),patch.object(runtime,'stop') as stop:
            response=self.client.put('/api/workspace/settings',json={'ai_api_key':'','ai_enabled':False})
            self.assertEqual(response.status_code,200,response.text)
            self.assertFalse(response.json()['ai_enabled']);stop.assert_not_called()

    def test_supported_model_selection_changes_budget_rates_without_enabling_ai(self):
        from research.config import ResearchConfig
        response=self.client.put('/api/workspace/settings',json={'ai_model':'claude-opus-4-6'})
        self.assertEqual(response.status_code,200,response.text)
        self.assertFalse(response.json()['ai_enabled'])
        self.assertEqual(response.json()['ai_model'],'claude-opus-4-6')
        config=ResearchConfig.from_env(settings=self.store.read())
        self.assertEqual(config.input_per_million,5)
        self.assertEqual(config.output_per_million,25)
        self.assertEqual(len(self.client.get('/api/workspace/ai-models').json()),4)
        self.assertEqual(self.client.put('/api/workspace/settings',json={'ai_model':'invented-model'}).status_code,422)
