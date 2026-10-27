"""Rule-based fresh news catalysts. Regular-session entries only; no AI key needed."""
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
from pathlib import Path
import re
from urllib.parse import urlencode
from urllib.request import Request, urlopen

POSITIVE = re.compile(r'\b(beats? (?:earnings|estimates|expectations)|raises? (?:guidance|outlook)|fda approv\w*|wins? (?:a |the )?(?:major |new )?contract|upgrad(?:e|es|ed) to (?:buy|outperform)|earnings beat)\b', re.I)
NEGATIVE = re.compile(r'\b(not|denies?|rumou?r|may|could|lawsuit|miss(?:es|ed)?|downgrad\w*|cuts? (?:guidance|outlook)|reject\w*)\b', re.I)

def eligible(item, now=None):
    now = now or datetime.now(timezone.utc)
    try:
        created = datetime.fromisoformat(item['created_at'].replace('Z','+00:00'))
        if created.tzinfo is None or not timedelta(0) <= now-created <= timedelta(hours=4): return False
        headline = item.get('headline','')
        return bool(POSITIVE.search(headline) and not NEGATIVE.search(headline))
    except (KeyError, TypeError, ValueError):
        return False

def fetch(symbols):
    """Bounded HTTP GETs, at most 50 symbols/batch; source data is untrusted text."""
    output = {}
    for offset in range(0, len(symbols), 50):
        params = urlencode(dict(symbols=','.join(symbols[offset:offset+50]), limit=50, sort='desc',
                                start=(datetime.now(timezone.utc)-timedelta(hours=4)).isoformat()))
        req = Request('https://data.alpaca.markets/v1beta1/news?'+params, headers={
            'APCA-API-KEY-ID':os.environ['APCA_API_KEY_ID'],
            'APCA-API-SECRET-KEY':os.environ['APCA_API_SECRET_KEY']})
        with urlopen(req, timeout=8) as response: items=json.load(response).get('news',[])
        for item in items:
            if not eligible(item): continue
            for symbol in item.get('symbols',[]):
                if symbol not in symbols or symbol in output: continue
                output[symbol] = dict(id=str(item.get('id') or hashlib.sha256(item['headline'].encode()).hexdigest()),
                                      headline=item['headline'][:300], created_at=item['created_at'])
    return output

def consume(symbol, item):
    """Persist intent before submission; never trade the same story twice per account."""
    path = os.environ.get('NEXLARA_RISK_STATE')
    if not path: return False
    target = Path(path).with_suffix('.news.json')
    previous = json.loads(target.read_text()) if target.exists() else {}
    now = datetime.now(timezone.utc)
    # Keep recent story intents; corrupt state raises and blocks news execution.
    previous = {k:v for k,v in previous.items() if now.timestamp()-float(v) < 7*86400}
    identity = symbol+':'+item['id']
    if identity in previous: return False
    previous[identity] = now.timestamp()
    temporary = target.with_suffix('.tmp')
    with temporary.open('w') as f:
        json.dump(previous,f); f.flush(); os.fsync(f.fileno())
    temporary.replace(target)
    return True
