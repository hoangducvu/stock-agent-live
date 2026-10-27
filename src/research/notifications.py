"""Asynchronous outgoing Slack notifications only; no Slack trade commands."""
import json
from urllib.parse import urlsplit

def validate_webhook(url):
    if not url:return ''
    parsed=urlsplit(url)
    if parsed.scheme!='https' or parsed.hostname!='hooks.slack.com' or not parsed.path.startswith('/services/') or parsed.query or parsed.fragment or parsed.username or parsed.port:
        raise ValueError('Use an HTTPS Slack incoming webhook from hooks.slack.com/services/.')
    return url

def enqueue(db,key,kind,payload):
    # Only deterministic broker/status events, not arbitrary AI prose.
    db.put('notification',key,dict(kind=kind,payload=payload))

def deliver(db,settings):
    webhook=validate_webhook(settings.get('slack_webhook',''))
    if not settings.get('slack_notifications') or not webhook:return
    from slack_sdk.webhook import WebhookClient
    client=WebhookClient(webhook,timeout=5,retry_handlers=[])
    for row in reversed(db.recent('notification',50)):
        key=row['key']
        if not db.claim('slack:'+key,lease_seconds=60):continue
        try:
            message=row['payload'];payload=message['payload']
            # Escape Slack markup for all external strings; no automatic mentions.
            text=('Nexlara PAPER · '+message['kind']+'\n'+json.dumps(payload,sort_keys=True))[:2500]
            text=text.replace('&','&amp;').replace('<','&lt;').replace('>','&gt;')
            response=client.send(text=text,unfurl_links=False,unfurl_media=False)
            if response.status_code!=200:raise RuntimeError('Slack delivery failed')
            db.finish('slack:'+key,True,{})
        except Exception as error:
            db.event('notification_failure',key,dict(type=type(error).__name__))
            db.finish('slack:'+key,False,{})


def execution_event(order_id,symbol,status,quantity,price,side):
    import os
    from pathlib import Path
    from .db import ResearchDB
    path=os.getenv('NEXLARA_RESEARCH_DB',str(Path(__file__).resolve().parents[1]/'data'/'research.sqlite3'))
    db=ResearchDB(path)
    payload=dict(symbol=symbol,status=status,filled_qty=quantity,fill_price=price,side=side,broker_order_id=order_id)
    key=order_id+':'+status+':'+str(quantity)
    db.event('broker_execution',key,payload)
    if quantity>0:enqueue(db,key,'Broker fill',payload)
