"""Limit-order lifecycle and atomic single-winner trigger."""
from __future__ import annotations
import os
from datetime import datetime,timezone
from core import db_runtime
class SQLiteLimitOrderStore:
 def __init__(self,path,timeout=10):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def create(self,*,user_id,currency,target_rate,direction,rub_amount,destination,payment_method,expires_at):
  exp=expires_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M:%S')
  with self._c() as c:q=c.execute("INSERT INTO limit_orders(user_id,currency,target_rate,direction,rub_amount,crypto_address,payment_method,expires_at) VALUES(?,?,?,?,?,?,?,?)",(user_id,currency,target_rate,direction,rub_amount,destination,payment_method,exp));c.commit();return int(q.lastrowid)
 def active(self):
  with self._c() as c:r=c.execute("SELECT id,user_id,currency,target_rate,direction,rub_amount,crypto_address,expires_at FROM limit_orders WHERE status='active' AND expires_at>CURRENT_TIMESTAMP").fetchall()
  k=('id','user_id','currency','target_rate','direction','rub_amount','destination','expires_at');return [dict(zip(k,x)) for x in r]
 def for_user(self,user_id,limit=10):
  with self._c() as c:return c.execute("SELECT id,currency,direction,target_rate,rub_amount,status,expires_at FROM limit_orders WHERE user_id=? AND status IN ('active','triggered') ORDER BY id DESC LIMIT ?",(user_id,int(limit))).fetchall()
 def cancel(self,ident,user_id=None):
  with self._c() as c:
   q=c.execute("UPDATE limit_orders SET status='cancelled' WHERE id=? AND status='active'"+(" AND user_id=?" if user_id is not None else ""),((ident,user_id) if user_id is not None else (ident,)));c.commit();return q.rowcount==1
 def trigger(self,*,ident,expected_expires_at,destination,agreed_rate,agreed_crypto_amount):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT user_id,currency,rub_amount FROM limit_orders WHERE id=? AND status='active' AND expires_at=? AND expires_at>CURRENT_TIMESTAMP",(ident,expected_expires_at)).fetchone()
   if not r:return {'action':'lost_race'}
   q=c.execute("INSERT INTO orders(user_id,currency,rub_amount,crypto_address,status,username,agreed_rate,agreed_crypto_amount,agreed_at) VALUES(?,?,?,?,'pending','limit_order',?,?,CURRENT_TIMESTAMP)",(r[0],r[1],r[2],destination,agreed_rate,agreed_crypto_amount));oid=int(q.lastrowid)
   changed=c.execute("UPDATE limit_orders SET status='triggered',triggered_at=CURRENT_TIMESTAMP,order_id=? WHERE id=? AND status='active' AND expires_at=?",(oid,ident,expected_expires_at)).rowcount
   if changed!=1:raise RuntimeError('limit_trigger_lost')
   c.commit();return {'action':'triggered','order_id':oid}
 def expire(self):
  with self._c() as c:q=c.execute("UPDATE limit_orders SET status='expired' WHERE status='active' AND expires_at<=CURRENT_TIMESTAMP");c.commit();return q.rowcount

class PostgresLimitOrderStore:
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def create(self,*,user_id,currency,target_rate,direction,rub_amount,destination,payment_method,expires_at):
  with self._c() as c,c.cursor() as q:
   q.execute("INSERT INTO limit_orders(user_id,currency,target_rate,direction,rub_amount,crypto_address,payment_method,expires_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",(user_id,currency,target_rate,direction,rub_amount,destination,payment_method,expires_at));return int(q.fetchone()['id'])
 def active(self):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT id,user_id,currency,target_rate,direction,rub_amount,crypto_address AS destination,expires_at FROM limit_orders WHERE status='active' AND expires_at>now()")
   return [dict(r) for r in q.fetchall()]
 def for_user(self,user_id,limit=10):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT id,currency,direction,target_rate,rub_amount,status,expires_at FROM limit_orders WHERE user_id=%s AND status IN ('active','triggered') ORDER BY id DESC LIMIT %s",(user_id,int(limit)))
   return [(r['id'],r['currency'],r['direction'],r['target_rate'],r['rub_amount'],r['status'],r['expires_at'].isoformat() if hasattr(r['expires_at'],'isoformat') else str(r['expires_at'])) for r in q.fetchall()]
 def cancel(self,ident,user_id=None):
  with self._c() as c,c.cursor() as q:
   if user_id is None:q.execute("UPDATE limit_orders SET status='cancelled' WHERE id=%s AND status='active'",(ident,))
   else:q.execute("UPDATE limit_orders SET status='cancelled' WHERE id=%s AND user_id=%s AND status='active'",(ident,user_id))
   return q.rowcount==1
 def trigger(self,*,ident,expected_expires_at,destination,agreed_rate,agreed_crypto_amount):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT user_id,currency,rub_amount FROM limit_orders WHERE id=%s AND status='active' AND expires_at=%s AND expires_at>now() FOR UPDATE",(ident,expected_expires_at));r=q.fetchone()
   if not r:return {'action':'lost_race'}
   q.execute("INSERT INTO orders(user_id,currency,rub_amount,crypto_address,status,username,agreed_rate,agreed_crypto_amount,agreed_at) VALUES(%s,%s,%s,%s,'pending','limit_order',%s,%s,now()) RETURNING order_id",(r['user_id'],r['currency'],r['rub_amount'],destination,agreed_rate,agreed_crypto_amount));oid=int(q.fetchone()['order_id'])
   q.execute("UPDATE limit_orders SET status='triggered',triggered_at=now(),order_id=%s WHERE id=%s AND status='active' AND expires_at=%s",(oid,ident,expected_expires_at))
   if q.rowcount!=1:raise RuntimeError('limit_trigger_lost')
   return {'action':'triggered','order_id':oid}
 def expire(self):
  with self._c() as c,c.cursor() as q:q.execute("UPDATE limit_orders SET status='expired' WHERE status='active' AND expires_at<=now()");return q.rowcount
def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteLimitOrderStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('LIMIT_ORDER_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_limit_order_store_not_enabled')
 return PostgresLimitOrderStore(url)
