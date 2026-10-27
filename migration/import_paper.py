"""Read credentials only from the pipe and persist an encrypted paper profile."""
import json
import math
from pathlib import Path
import sys
sys.path.insert(0, '/app')
from backend.settings_store import SettingsStore

payload=json.load(sys.stdin)
equity=float(payload['equity'])
if not math.isfinite(equity) or equity<=0 or not payload.get('api_key') or not payload.get('secret_key') or not payload.get('paper_account_id'):
    sys.exit('Invalid paper profile. Nothing saved.')
strategy=payload.get('strategy','ema_vwap')
if strategy not in {'ema_vwap','orb','rsi'}:sys.exit('Unsupported strategy. Nothing saved.')
store=SettingsStore('/app/data')
values={**store.read(), 'api_key':payload['api_key'], 'secret_key':payload['secret_key'],
        'paper_account_id':payload['paper_account_id'], 'strategy':strategy,
        'max_order_value':250.0, 'max_position_pct':5.0, 'max_daily_loss_pct':2.0,
        'max_positions':3, 'starting_capital':equity, 'halt_equity':round(equity*.9,2),
        'close_on_stop':True}
store.write(values)
print('Paper connection encrypted and saved. Keys were not displayed.')
print('Position budget: 5% of equity, capped at $250 per order; maximum 3 positions.')
print('Daily loss limit: 2%; absolute equity halt: 90% of migration equity.')
