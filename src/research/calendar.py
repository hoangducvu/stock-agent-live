"""Broker-published US exchange sessions; never infer sessions from weekdays."""
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo
ET=ZoneInfo('America/New_York')
@dataclass(frozen=True)
class Session:
    day: str
    opening: datetime
    closing: datetime
    def schedule(self,config):
        day=self.opening.date()
        pre=datetime.combine(day,time.fromisoformat(config.premarket_time),ET)
        configured=datetime.combine(day,time.fromisoformat(config.postmarket_time),ET)
        normal_close=datetime.combine(day,time(16),ET)
        delay=max(configured-normal_close,timedelta(minutes=15))
        post=self.closing+delay
        entry=max(self.opening+timedelta(minutes=config.opening_minutes),datetime.combine(day,time.fromisoformat(config.entry_start),ET))
        # Explicitly setting both restrictions to market-open enables early entries.
        return dict(premarket=pre,entry=entry,postmarket=post)
class ExchangeCalendar:
    def __init__(self,fetch,db=None):self.fetch=fetch;self.db=db
    def session(self,day):
        key=str(day)
        rows=self.db.get('calendar',key) if self.db else None
        if rows is None:
            rows=self.fetch(key,key)
            if self.db:self.db.put('calendar',key,rows)
        for row in rows:
            if row['date']==key:
                def stamp(value):return datetime.combine(datetime.fromisoformat(key).date(),time.fromisoformat(value),ET)
                return Session(key,stamp(row['open']),stamp(row['close']))
        return None
