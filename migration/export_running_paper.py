"""Pipe directly to import_paper.py; output contains secrets. Never run alone."""
import json
import os
from pathlib import Path
import sys
import urllib.request

def main():
    candidates=[]
    for proc in Path('/proc').glob('[0-9]*'):
        try:
            args=proc.joinpath('cmdline').read_bytes().split(b'\0')
            if b'/app/main.py' not in args:
                continue
            env=dict(item.split(b'=',1) for item in proc.joinpath('environ').read_bytes().split(b'\0') if b'=' in item)
            env={k.decode():v.decode() for k,v in env.items()}
            candidates.append(env)
        except (OSError, UnicodeError):
            continue
    if len(candidates)!=1:
        sys.exit('Expected exactly one running engine; connection transfer aborted before stopping it.')
    env=candidates[0]
    if env.get('TRADING_MODE','').lower()!='paper' or env.get('ALPACA_PAPER','true').lower()!='true':
        sys.exit('Connection transfer requires an explicitly PAPER engine.')
    key=env.get('APCA_API_KEY_ID') or env.get('ALPACA_API_KEY')
    secret=env.get('APCA_API_SECRET_KEY') or env.get('ALPACA_SECRET_KEY')
    if not key or not secret:
        sys.exit('Running engine has no transferable broker credentials.')
    req=urllib.request.Request('https://paper-api.alpaca.markets/v2/account',headers={'APCA-API-KEY-ID':key,'APCA-API-SECRET-KEY':secret})
    try:
        with urllib.request.urlopen(req,timeout=15) as response:account=json.load(response)
        equity=float(account['equity'])
        if account.get('status')!='ACTIVE' or not account.get('id') or not equity>0:
            raise ValueError()
    except Exception:
        sys.exit('Paper account verification failed. Connection transfer aborted; engine untouched.')
    json.dump(dict(api_key=key,secret_key=secret,paper_account_id=account['id'],equity=equity,strategy=env.get('STRATEGY','ema_vwap')),sys.stdout)

if __name__=='__main__':main()
