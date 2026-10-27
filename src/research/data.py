"""Read-only Alpaca + explicit point-in-time evidence adapters. No orders here."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import math
import os
import urllib.parse
import urllib.request
import urllib.error
import time
from .calendar import ET

class AlpacaResearchData:
    def __init__(self,values):self.values=values
    def get(self,path,params=None,data=False):
        base='https://data.alpaca.markets' if data else 'https://paper-api.alpaca.markets'
        url=base+path+('?' + urllib.parse.urlencode(params) if params else '')
        request=urllib.request.Request(url,headers={'APCA-API-KEY-ID':self.values['api_key'],'APCA-API-SECRET-KEY':self.values['secret_key']})
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request,timeout=15) as response:return json.load(response)
            except urllib.error.HTTPError as error:
                if error.code not in {429,500,502,503,504} or attempt==2:raise
                try:delay=min(60,max(1,float(error.headers.get('Retry-After',2**attempt))))
                except ValueError:delay=2**attempt
                time.sleep(delay)
            except (urllib.error.URLError,TimeoutError):
                if attempt==2:raise
                time.sleep(2**attempt)
    def calendar(self,start,end):return self.get('/v2/calendar',dict(start=start,end=end))
    def universe(self):
        """Every active, broker-tradable US equity; no ticker or exchange cutoff.

        Historical AI_UNIVERSE_LIMIT / AI_UNIVERSE_SYMBOLS settings no longer
        restrict coverage. Ordering only makes traversal and audit logs stable.
        """
        assets=self.get('/v2/assets',dict(status='active',asset_class='us_equity'))
        import re
        self.asset_metadata={a['symbol']:{'instrument_hint':'fund_name_match' if re.search(r'\b(etf|etn|fund|ishares)\b',(a.get('name') or ''),re.I) else 'unknown'}
                             for a in assets if isinstance(a.get('symbol'),str)}
        return sorted({a['symbol'] for a in assets
                       if a.get('tradable') and a.get('status')=='active'
                       and a.get('class','us_equity')=='us_equity'
                       and isinstance(a.get('symbol'),str) and a['symbol']})
    def daily(self,symbols,through):
        # End at next midnight ET; never include later sessions in a replay.
        start=(through-timedelta(days=450)).date().isoformat()
        boundary=(through+timedelta(days=1)).replace(hour=0,minute=0,second=0,microsecond=0)
        end=(boundary-timedelta(microseconds=1)).isoformat()
        result={}
        for offset in range(0,len(symbols),25):
            params=dict(symbols=','.join(symbols[offset:offset+25]),timeframe='1Day',start=start,end=end,feed='iex',adjustment='raw',limit=10000,sort='asc')
            seen_tokens=set()
            for _ in range(20):
                payload=self.get('/v2/stocks/bars',params,data=True)
                for symbol,bars in payload.get('bars',{}).items():
                    result.setdefault(symbol,[]).extend(b for b in bars
                        if datetime.fromisoformat(b['t'].replace('Z','+00:00'))<boundary)
                token=payload.get('next_page_token')
                if not token:break
                if token in seen_tokens:raise RuntimeError('Repeated daily-bar pagination token')
                seen_tokens.add(token)
                params['page_token']=token
            else:raise RuntimeError('Bar pagination incomplete')
        return result
    def portfolio(self):
        account=self.get('/v2/account');positions=self.get('/v2/positions')
        return dict(account={k:account.get(k) for k in ('id','equity','cash','buying_power','status')},positions=positions)
    def snapshot(self,symbol):return self.get('/v2/stocks/snapshots',dict(symbols=symbol,feed='iex'),data=True).get(symbol,{})
    def news(self,symbols):
        return self.get('/v1beta1/news',dict(symbols=','.join(symbols),limit=50,start=(datetime.now(timezone.utc)-timedelta(hours=16)).isoformat()),data=True).get('news',[])

    def intraday(self,symbols):
        result={}
        for offset in range(0,len(symbols),10):
            params=dict(symbols=','.join(symbols[offset:offset+10]),timeframe='5Min',start=(datetime.now(timezone.utc)-timedelta(days=8)).isoformat(),feed='iex',limit=10000)
            for _ in range(20):
                payload=self.get('/v2/stocks/bars',params,data=True)
                for symbol,bars in payload.get('bars',{}).items():result.setdefault(symbol,[]).extend(bars)
                token=payload.get('next_page_token')
                if not token:break
                params['page_token']=token
            else:raise RuntimeError('Intraday pagination incomplete')
        return result

class EvidenceFile:
    """Explicit adapter for licensed/provider-fed PIT fundamentals/events.
    JSON: {ticker:{as_of, observed_at, sector, next_earnings, fundamentals,
                   source_references:[...]}}. Missing evidence is never invented.
    """
    def __init__(self,path=None):self.path=path or os.getenv('AI_EVIDENCE_FILE','')
    def get(self,ticker,now):
        if not self.path:return None
        values=json.loads(Path(self.path).read_text());record=values.get(ticker)
        if not record:return None
        observed=datetime.fromisoformat(record['observed_at'].replace('Z','+00:00'))
        as_of=datetime.fromisoformat(record['as_of'].replace('Z','+00:00'))
        if observed.tzinfo is None or as_of.tzinfo is None or observed>now or as_of>now or (now-observed).days>7 or (now-as_of).days>120:return None
        if not record.get('source_references'):return None
        return record

def summarize_bars(ticker,bars,benchmark_return=0):
    import pandas as pd
    import indicators as ind
    if len(bars)<201:return None
    frame=pd.DataFrame(bars).drop_duplicates('t').sort_values('t')
    if len(frame)<201:return None
    close=frame['c'].astype(float);volume=frame['v'].astype(float)
    price=float(close.iloc[-1]);sma50=float(close.rolling(50).mean().iloc[-1]);sma200=float(close.rolling(200).mean().iloc[-1])
    average=float((close*volume).tail(20).mean());momentum=float(price/close.iloc[-21]-1)
    atr=float(ind.atr(frame.rename(columns={'h':'High','l':'Low','c':'Close'}),14).iloc[-1])
    rsi=float(ind.rsi(close,14).iloc[-1]);macd=ind.ema(close,12)-ind.ema(close,26)
    data=dict(ticker=ticker,price=price,sma50=sma50,sma200=sma200,rsi=rsi,macd=float(macd.iloc[-1]),atr=atr,
              atr_pct=atr/price,average_dollar_volume=average,return_20d=momentum,relative_strength=momentum-benchmark_return,
              return_1d=float(price/close.iloc[-2]-1),relative_volume=float(volume.iloc[-1]/volume.tail(20).mean()),
              data_timestamp=frame['t'].iloc[-1],source_references=['alpaca:iex:daily:'+ticker])
    if any(isinstance(v,float) and not math.isfinite(v) for v in data.values()):return None
    return data

def screen(summaries,evidence,config,now):
    ranked=[];rejections=[]
    for original in summaries:
        row=dict(original);reason=[];details=[]
        def reject(code,message):
            if code not in reason:reason.append(code)
            details.append(dict(code=code,message=message))
        if row['price']<config.min_price:
            reject('price',f"Price ${row['price']:.2f} is below the ${config.min_price:.2f} minimum.")
        if row['average_dollar_volume']<config.min_dollar_volume:
            reject('liquidity',f"20-day average daily dollar volume ${row['average_dollar_volume']:,.0f} is below ${config.min_dollar_volume:,.0f}.")
        if row['price']<row['sma200']:
            reject('trend/relative_strength',f"Price ${row['price']:.2f} is below the 200-day average ${row['sma200']:.2f}.")
        if row['sma50']<row['sma200']:
            reject('trend/relative_strength',f"50-day average ${row['sma50']:.2f} is below the 200-day average ${row['sma200']:.2f}.")
        if row['relative_strength']<config.min_relative_strength:
            reject('trend/relative_strength',f"20-day return relative to SPY {row['relative_strength']:+.2%} is below {config.min_relative_strength:+.2%}.")
        if not config.rsi_min<=row['rsi']<=config.rsi_max:
            reject('momentum/volatility',f"RSI {row['rsi']:.2f} is outside the {config.rsi_min:g}–{config.rsi_max:g} range.")
        if row['atr_pct']>config.max_atr_pct:
            reject('momentum/volatility',f"ATR/price {row['atr_pct']:.2%} exceeds the {config.max_atr_pct:.2%} limit.")
        record=evidence.get(row['ticker'],now)
        missing=[]
        if not record or not record.get('fundamentals'):
            if config.require_fundamentals:missing.append('fundamentals')
        if not record or not record.get('next_earnings'):
            if config.require_earnings:missing.append('earnings')
        if record:
            row['sector']=record.get('sector');row['fundamentals']=record.get('fundamentals',{})
            row['next_earnings']=record.get('next_earnings')
            row['source_references']+=record['source_references']
            if record.get('next_earnings'):
                days=(datetime.fromisoformat(record['next_earnings']).date()-now.astimezone(ET).date()).days
                if days<0:missing.append('stale_earnings')
                elif days<=config.earnings_buffer_days:
                    reject('earnings_proximity',f"Earnings are {days} days away, within the {config.earnings_buffer_days}-day exclusion window.")
        row['missing_required_evidence']=missing
        for code in missing:
            reject(code,{'fundamentals':'No validated financial facts are available.',
                         'earnings':'No verified upcoming earnings date is available.',
                         'stale_earnings':'The saved earnings date has already passed.'}[code])
        row['score']=round(row['relative_strength']*100+min(row['return_20d']*100,20)+(row['price']/row['sma200']-1)*10-row['atr_pct']*100,4)
        if reason:rejections.append(dict(ticker=row['ticker'],reasons=reason,reason_details=details))
        else:ranked.append(row)
    ordered=sorted(ranked,key=lambda r:(-r['score'],r['ticker']))
    for rank,row in enumerate(ordered[config.candidates:],start=config.candidates+1):
        rejections.append(dict(ticker=row['ticker'],reasons=['shortlist_limit'],reason_details=[dict(code='shortlist_limit',
            message=f"Passed technical filters; score {row['score']:.4f} ranked {rank}, outside the top {config.candidates} research slots.")],score=row['score'],rank=rank))
    return ordered[:config.candidates],rejections
