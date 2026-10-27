"""WAL SQLite research/audit store; reservations and claims are cross-process atomic."""
import json
from pathlib import Path
import sqlite3
import time
import uuid
from contextlib import contextmanager

class ResearchDB:
    def __init__(self,path):
        self.path=Path(path);self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.connect() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY,ts REAL,kind TEXT,key TEXT,payload TEXT);
            CREATE TABLE IF NOT EXISTS objects(kind TEXT,key TEXT,ts REAL,expires REAL,payload TEXT,PRIMARY KEY(kind,key));
            CREATE TABLE IF NOT EXISTS usage(id TEXT PRIMARY KEY,day TEXT,reserved REAL,cost REAL,input_tokens INTEGER,output_tokens INTEGER,status TEXT,ts REAL);
            CREATE TABLE IF NOT EXISTS jobs(key TEXT PRIMARY KEY,status TEXT,lease REAL,attempts INTEGER,payload TEXT);
            CREATE TABLE IF NOT EXISTS signals(key TEXT PRIMARY KEY,day TEXT,ticker TEXT,strategy TEXT,status TEXT,ts REAL,payload TEXT);
            CREATE TABLE IF NOT EXISTS orders(key TEXT PRIMARY KEY,ts REAL,status TEXT,broker_id TEXT,payload TEXT);
            ''')
            columns={r['name'] for r in db.execute('PRAGMA table_info(usage)')}
            for name in ('searches_reserved','searches'):
                if name not in columns:db.execute('ALTER TABLE usage ADD COLUMN '+name+' INTEGER')
    @contextmanager
    def connect(self):
        db=sqlite3.connect(str(self.path),timeout=10);db.row_factory=sqlite3.Row
        db.execute('PRAGMA journal_mode=WAL');db.execute('PRAGMA busy_timeout=10000')
        try:
            with db:yield db
        finally:db.close()
    def event(self,kind,key,payload):
        with self.connect() as db:db.execute('INSERT INTO events(ts,kind,key,payload) VALUES(?,?,?,?)',(time.time(),kind,key,json.dumps(payload,allow_nan=False)))
    def put(self,kind,key,payload,expires=None,now=None):
        with self.connect() as db:db.execute('INSERT OR REPLACE INTO objects VALUES(?,?,?,?,?)',(kind,key,now or time.time(),expires,json.dumps(payload,allow_nan=False)))
    def get(self,kind,key,now=None):
        with self.connect() as db:row=db.execute('SELECT * FROM objects WHERE kind=? AND key=?',(kind,key)).fetchone()
        if not row or (row['expires'] is not None and row['expires']<=(now or time.time())):return None
        return json.loads(row['payload'])
    def delete(self,kind,key):
        with self.connect() as db:db.execute('DELETE FROM objects WHERE kind=? AND key=?',(kind,key))
    def recent(self,kind,limit=20):
        with self.connect() as db:rows=db.execute('SELECT * FROM objects WHERE kind=? AND (expires IS NULL OR expires>?) ORDER BY ts DESC LIMIT ?',(kind,time.time(),limit)).fetchall()
        return [dict(ts=r['ts'],key=r['key'],payload=json.loads(r['payload'])) for r in rows]
    def reserve(self,day,amount,max_calls,max_dollars,searches=0,max_searches=None):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            count,total=db.execute('SELECT COUNT(*),COALESCE(SUM(CASE WHEN cost IS NULL THEN reserved ELSE cost END),0) FROM usage WHERE day=?',(day,)).fetchone()
            if count>=max_calls or total+amount>max_dollars:return None
            used_searches=db.execute('SELECT COALESCE(SUM(COALESCE(searches,searches_reserved,0)),0) FROM usage WHERE day=?',(day,)).fetchone()[0]
            if max_searches is not None and used_searches+searches>max_searches:return None
            key=uuid.uuid4().hex
            db.execute('INSERT INTO usage(id,day,reserved,cost,input_tokens,output_tokens,status,ts,searches_reserved) VALUES(?,?,?,?,?,?,?,?,?)',(key,day,amount,None,0,0,'reserved',time.time(),searches))
            return key
    def settle(self,key,cost,input_tokens,output_tokens,status,searches=None):
        with self.connect() as db:db.execute('UPDATE usage SET cost=?,input_tokens=?,output_tokens=?,status=?,searches=? WHERE id=?',(cost,input_tokens,output_tokens,status,searches,key))
    def usage(self,day):
        with self.connect() as db:
            row=db.execute('SELECT COUNT(*) calls,COALESCE(SUM(COALESCE(cost,reserved)),0) cost,COALESCE(SUM(input_tokens),0) input_tokens,COALESCE(SUM(output_tokens),0) output_tokens,COALESCE(SUM(COALESCE(searches,searches_reserved,0)),0) searches FROM usage WHERE day=?',(day,)).fetchone()
        return dict(row)
    def claim(self,key,lease_seconds=180,now=None,max_attempts=3):
        now=now or time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE');row=db.execute('SELECT * FROM jobs WHERE key=?',(key,)).fetchone()
            if row and (row['status']=='done' or row['lease']>now):return False
            attempts=(row['attempts']+1) if row else 1
            if max_attempts is not None and attempts>max_attempts:return False
            db.execute('INSERT OR REPLACE INTO jobs VALUES(?,?,?,?,?)',(key,'running',now+lease_seconds,attempts,'{}'));return True
    def finish(self,key,success,payload):
        with self.connect() as db:db.execute('UPDATE jobs SET status=?,lease=?,payload=? WHERE key=?',('done' if success else 'retry',0 if success else time.time()+300,json.dumps(payload),key))
    def queue_signal(self,key,day,ticker,strategy,payload):
        with self.connect() as db:
            result=db.execute('INSERT OR IGNORE INTO signals VALUES(?,?,?,?,?,?,?)',(key,day,ticker,strategy,'pending',time.time(),json.dumps(payload,allow_nan=False)))
            return result.rowcount==1
    def pending(self,day):
        with self.connect() as db:rows=db.execute("SELECT * FROM signals WHERE day=? AND status='pending' ORDER BY ts LIMIT 15",(day,)).fetchall()
        return [dict(r, payload=json.loads(r['payload'])) for r in rows]
    def signal_status(self,key,status):
        with self.connect() as db:db.execute('UPDATE signals SET status=? WHERE key=?',(status,key))
    def order_intent(self,key,payload):
        with self.connect() as db:
            result=db.execute('INSERT OR IGNORE INTO orders VALUES(?,?,?,?,?)',(key,time.time(),'intent',None,json.dumps(payload,allow_nan=False)))
            return result.rowcount==1
    def reserve_entry(self,key,payload,checks):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if db.execute('SELECT 1 FROM orders WHERE key=?',(key,)).fetchone():return False
            positions=set(checks.get('broker_symbols',[]));pending_total=0.;pending_sector=0.
            for row in db.execute("SELECT payload FROM orders WHERE status!='released'"):
                prior=json.loads(row['payload'])
                if prior.get('scope')!=payload['scope'] or prior.get('ticker') in positions:continue
                amount=float(prior.get('reserved_notional',0))
                pending_total+=amount
                if prior.get('sector')==payload.get('sector'):pending_sector+=amount
            amount=payload['reserved_notional']
            if pending_total+amount>float(checks.get('portfolio_room',0)) or pending_sector+amount>float(checks.get('sector_room',0)):return False
            db.execute('INSERT INTO orders VALUES(?,?,?,?,?)',(key,time.time(),'intent',None,json.dumps(payload,allow_nan=False)))
            return True
    def reconcile_positions(self,scope,symbols,open_symbols):
        with self.connect() as db:
            for row in db.execute('SELECT key,status,payload FROM orders').fetchall():
                payload=json.loads(row['payload'])
                if payload.get('scope')!=scope:continue
                symbol=payload.get('ticker')
                if symbol in symbols and row['status']=='filled':
                    db.execute("UPDATE orders SET status='broker_observed' WHERE key=?",(row['key'],))
                elif row['status']=='broker_observed' and symbol not in symbols and symbol not in open_symbols:
                    db.execute("UPDATE orders SET status='released' WHERE key=?",(row['key'],))
    def order_result(self,key,status,broker_id=None,payload=None):
        with self.connect() as db:
            row=db.execute('SELECT payload FROM orders WHERE key=?',(key,)).fetchone()
            combined=json.loads(row['payload']) if row else {}
            combined['execution']=payload or {}
            db.execute('UPDATE orders SET status=?,broker_id=?,payload=? WHERE key=?',(status,broker_id,json.dumps(combined),key))
