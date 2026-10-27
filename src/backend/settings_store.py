"""Encrypted, durable configuration for the single-user private deployment."""
import json
import os
import sqlite3
from pathlib import Path
from cryptography.fernet import Fernet
from strategy_catalog import IDS

DEFAULTS = dict(strategy='ema_vwap', max_order_value=10000.0, max_position_pct=5.0,
                max_daily_loss_pct=2.0, max_positions=20, starting_capital=5000.0,
                halt_equity=4500.0, close_on_stop=True, strategies=IDS,
                shorts_enabled=True, news_enabled=True, sizing_basis='buying_power', schema_version=5, position_size_multiplier=10.0, allocation_mode='fill_slots', buying_power_reserve_pct=5.0, max_gross_exposure_pct=400.0,
                slack_notifications=False, slack_webhook='', slack_channel='', ai_enabled=False, ai_api_key='', ai_model='claude-haiku-4-5-20251001')

class SettingsStore:
    def __init__(self, directory):
        self.directory = Path(directory)

    def _connect(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(str(self.directory / 'settings.sqlite3'), timeout=10)
        db.execute('CREATE TABLE IF NOT EXISTS settings (id INTEGER PRIMARY KEY CHECK(id=1), payload BLOB NOT NULL)')
        os.chmod(self.directory / 'settings.sqlite3', 0o600)
        return db

    def _cipher(self):
        self.directory.mkdir(parents=True, exist_ok=True)
        key_path = self.directory / 'settings.key'
        try:
            fd = os.open(str(key_path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            pass
        else:
            with os.fdopen(fd, 'wb') as f:
                f.write(Fernet.generate_key())
                f.flush()
                os.fsync(f.fileno())
        return Fernet(key_path.read_bytes())

    def read(self):
        with self._connect() as db:
            row = db.execute('SELECT payload FROM settings WHERE id=1').fetchone()
        saved = json.loads(self._cipher().decrypt(row[0])) if row else {}
        values = {**DEFAULTS, **saved}
        if saved.get('schema_version', 0) < 3:
            # User explicitly requested every strategy, shorts, news and BP sizing.
            values.update(strategies=list(IDS), shorts_enabled=True, news_enabled=True,
                          sizing_basis='buying_power', schema_version=3,
                slack_notifications=False, slack_webhook='', slack_channel='', ai_enabled=False, ai_api_key='', ai_model='claude-haiku-4-5-20251001')
            values['max_order_value'] = max(float(values['max_order_value']), 1000.0)
        if saved.get('schema_version',0)<4:
            # User explicitly selected margin buying power and more positions.
            values.update(schema_version=4,allocation_mode='fill_slots',max_positions=20,
                          buying_power_reserve_pct=5.0,max_gross_exposure_pct=400.0)
        if saved.get('schema_version',0)<5:
            values.update(schema_version=5,position_size_multiplier=10.0,max_order_value=10000.0)
        if not values.get('ai_api_key','').strip():values['ai_enabled']=False
        return values

    def write(self, values):
        payload = self._cipher().encrypt(json.dumps(values).encode())
        with self._connect() as db:
            db.execute('INSERT OR REPLACE INTO settings VALUES (1, ?)', (payload,))

    def public(self):
        values = self.read()
        connected = bool(values.pop('api_key', '') and values.pop('secret_key', ''))
        values.pop('secret_key', None)
        values.pop('api_key', None)
        values['ai_configured'] = bool(values.pop('ai_api_key', '').strip())
        if not values['ai_configured']:values['ai_enabled']=False
        values['slack_configured'] = bool(values.pop('slack_webhook', ''))
        return {**values, 'credentials_saved': connected, 'paper': True}
