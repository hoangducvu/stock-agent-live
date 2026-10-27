#!/usr/bin/env bash
# Read-only live checks; safe while the trading engine is running.
set -euo pipefail
python3 - <<'PY'
import json
from urllib.request import urlopen
from urllib.error import HTTPError,URLError
from datetime import datetime
from zoneinfo import ZoneInfo
base='http://127.0.0.1:8080/api/'
failed=[]
def get(path):
    try:
        with urlopen(base+path,timeout=45) as response:return json.load(response)
    except (HTTPError,URLError,TimeoutError,ValueError) as error:
        print(path+': unavailable ('+type(error).__name__+')');failed.append(path);return None
health=get('health')
if health:print('API:',health.get('status'),'Engine running:',health.get('bot_running'))
settings=get('workspace/settings')
if settings:print('Sizing:',settings.get('position_size_multiplier'),'x; order cap:',settings.get('max_order_value'),'Paper:',settings.get('paper'))
status=get('workspace/status')
if status:
    state=status.get('state') or {}
    policy=state.get('intraday_policy') or ('not applicable - engine stopped' if not status.get('running') else 'not reported yet - waiting for engine state')
    print('Engine:',status.get('running'),'State timestamp:',state.get('timestamp'),'Risk halted:',state.get('halted'),'Intraday policy:',policy)
snapshot=get('workspace/account-snapshot')
if snapshot:
    account=snapshot.get('account') or {};clock=snapshot.get('clock') or {}
    print('Broker status:',account.get('status'),'Equity:',account.get('equity'),'Buying power:',account.get('buying_power'))
    print('Open positions:',len(snapshot.get('positions') or []),'Recent orders:',len(snapshot.get('orders') or []),'Market open:',clock.get('is_open'))
    if clock.get('next_open'):
        opening=datetime.fromisoformat(clock['next_open'].replace('Z','+00:00'))
        print('Next open in Malta:',opening.astimezone(ZoneInfo('Europe/Malta')).isoformat())
summary=get('workspace/daily-summary')
if summary:
    report=summary.get('report')
    if report:
        print('Current account closing summary:',report.get('date'),'Equity:',report.get('closing_equity'),'Account P&L:',report.get('account_pnl'),'Fills:',report.get('fills'))
        if settings and report.get('account_id')!=settings.get('paper_account_id'):
            print('ERROR: summary account mismatch');failed.append('summary-account')
    else:print('Summary:',summary.get('detail'))
if failed:raise SystemExit('Some read-only checks failed; no services or trading settings were changed.')
print('Read-only API checks passed. No orders or settings were changed.')
PY
