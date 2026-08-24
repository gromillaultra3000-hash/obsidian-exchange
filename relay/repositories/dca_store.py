"""DCA schedule lifecycle and atomic due-run order creation."""
from __future__ import annotations
import os
from datetime import datetime,timezone
from core import db_runtime

class SQLiteDcaStore:
 def __init__(self,path:str,*,timeout:float=10):self.path,self.timeout=path,timeout
 def _connect(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def create(self,*,user_id:int,currency:str,rub_amount:float,destination:str,interval_days:int,next_run:datetime):
  value=next_run.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
  with self._connect() as c:
   q=c.execute("INSERT INTO dca_schedules(user_id,currency,rub_amount,crypto_address,interval_days,next_run) VALUES(?,?,?,?,?,?)",(user_id,currency,rub_amount,destination,interval_days,value));c.commit();return int(q.lastrowid)
 def due(self,limit=100):
  with self._connect() as c:r=c.execute("SELECT id,user_id,currency,rub_amount,crypto_address,interval_days,next_run FROM dca_schedules WHERE status='active' AND next_run<=CURRENT_TIMESTAMP ORDER BY next_run,id LIMIT ?",(int(limit),)).fetchall()
  keys=('id','user_id','currency','rub_amount','destination','interval_days','next_run');return [dict(zip(keys,x)) for x in r]
 def for_user(self,user_id:int,limit=10):
  with self._connect() as c:return c.execute("SELECT id,currency,rub_amount,interval_days,next_run,runs_total,status FROM dca_schedules WHERE user_id=? ORDER BY id DESC LIMIT ?",(user_id,int(limit))).fetchall()
 def cancel(self,schedule_id:int,user_id:int|None=None):
  with self._connect() as c:
   if user_id is None:q=c.execute("UPDATE dca_schedules SET status='cancelled' WHERE id=? AND status='active'",(schedule_id,))
   else:q=c.execute("UPDATE dca_schedules SET status='cancelled' WHERE id=? AND user_id=? AND status='active'",(schedule_id,user_id))
   c.commit();return q.rowcount==1
 def run_due(self,*,schedule_id:int,expected_next_run:str,destination:str,agreed_rate:float,agreed_crypto_amount:float,next_run:datetime):
  value=next_run.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
  with self._connect() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT user_id,currency,rub_amount,interval_days FROM dca_schedules WHERE id=? AND status='active' AND next_run=? AND next_run<=CURRENT_TIMESTAMP",(schedule_id,expected_next_run)).fetchone()
   if not r:return {'action':'lost_race'}
   q=c.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,agreed_rate,agreed_crypto_amount,agreed_at) VALUES(?,?,?,?,?,'pending',?,?,CURRENT_TIMESTAMP)",(r[0],f'dca_{schedule_id}',r[1],r[2],destination,agreed_rate,agreed_crypto_amount));oid=int(q.lastrowid)
   changed=c.execute("UPDATE dca_schedules SET next_run=?,runs_total=runs_total+1 WHERE id=? AND status='active' AND next_run=?",(value,schedule_id,expected_next_run)).rowcount
   if changed!=1:raise RuntimeError('dca_advance_lost')
   c.commit();return {'action':'created','order_id':oid,'user_id':r[0],'currency':r[1],'rub_amount':r[2]}

class PostgresDcaStore:
 def __init__(self,dsn:str):self.dsn=dsn
 def _connect(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def create(self,*,user_id:int,currency:str,rub_amount:float,destination:str,interval_days:int,next_run:datetime):
  with self._connect() as c,c.cursor() as q:
   q.execute("INSERT INTO dca_schedules(user_id,currency,rub_amount,crypto_address,interval_days,next_run) VALUES(%s,%s,%s,%s,%s,%s) RETURNING id",(user_id,currency,rub_amount,destination,interval_days,next_run))
   return int(q.fetchone()['id'])
 def due(self,limit=100):
  with self._connect() as c,c.cursor() as q:
   q.execute("SELECT id,user_id,currency,rub_amount,crypto_address AS destination,interval_days,next_run FROM dca_schedules WHERE status='active' AND next_run<=now() ORDER BY next_run,id LIMIT %s",(int(limit),))
   return [dict(r) for r in q.fetchall()]
 def for_user(self,user_id:int,limit=10):
  with self._connect() as c,c.cursor() as q:
   q.execute("SELECT id,currency,rub_amount,interval_days,next_run,runs_total,status FROM dca_schedules WHERE user_id=%s ORDER BY id DESC LIMIT %s",(user_id,int(limit)))
   return [(r['id'],r['currency'],r['rub_amount'],r['interval_days'],r['next_run'].isoformat() if hasattr(r['next_run'],'isoformat') else str(r['next_run']),r['runs_total'],r['status']) for r in q.fetchall()]
 def cancel(self,schedule_id:int,user_id:int|None=None):
  with self._connect() as c,c.cursor() as q:
   if user_id is None:q.execute("UPDATE dca_schedules SET status='cancelled' WHERE id=%s AND status='active'",(schedule_id,))
   else:q.execute("UPDATE dca_schedules SET status='cancelled' WHERE id=%s AND user_id=%s AND status='active'",(schedule_id,user_id))
   return q.rowcount==1
 def run_due(self,*,schedule_id:int,expected_next_run,destination:str,agreed_rate:float,agreed_crypto_amount:float,next_run:datetime):
  with self._connect() as c,c.cursor() as q:
   q.execute("SELECT user_id,currency,rub_amount,interval_days FROM dca_schedules WHERE id=%s AND status='active' AND next_run=%s AND next_run<=now() FOR UPDATE",(schedule_id,expected_next_run));r=q.fetchone()
   if not r:return {'action':'lost_race'}
   q.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,agreed_rate,agreed_crypto_amount,agreed_at) VALUES(%s,%s,%s,%s,%s,'pending',%s,%s,now()) RETURNING order_id",(r['user_id'],f'dca_{schedule_id}',r['currency'],r['rub_amount'],destination,agreed_rate,agreed_crypto_amount));oid=int(q.fetchone()['order_id'])
   q.execute("UPDATE dca_schedules SET next_run=%s,runs_total=runs_total+1 WHERE id=%s AND status='active' AND next_run=%s",(next_run,schedule_id,expected_next_run))
   if q.rowcount!=1:raise RuntimeError('dca_advance_lost')
   return {'action':'created','order_id':oid,'user_id':r['user_id'],'currency':r['currency'],'rub_amount':r['rub_amount']}

def from_environment(*,sqlite_path:str):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteDcaStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('DCA_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_dca_store_not_enabled')
 return PostgresDcaStore(url)
