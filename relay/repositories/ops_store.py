"""Durable operational flags and append-only application audit events."""
from __future__ import annotations
import os
from core import db_runtime
class SQLiteOpsStore:
 def __init__(self,path:str,*,timeout:float=5):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def get_flag(self,key):
  with self._c() as c:r=c.execute("SELECT value FROM system_flags WHERE key=?",(key,)).fetchone();return r[0] if r else None
 def set_flags(self,values):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE')
   for key,value in values.items():c.execute("INSERT INTO system_flags(key,value,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=CURRENT_TIMESTAMP",(key,str(value)))
   c.commit();return True
 def audit(self,*,event,details):
  with self._c() as c:c.execute("INSERT INTO audit_log(event,details) VALUES(?,?)",(event,details));c.commit()
 def cleanup_audit(self,days=90):
  with self._c() as c:q=c.execute("DELETE FROM audit_log WHERE created_at<datetime('now',?)",(f'-{int(days)} days',));c.commit();return q.rowcount
 def payout_totals(self,hours):
  with self._c() as c:r=c.execute("SELECT COALESCE(SUM(rub_amount),0),COUNT(*) FROM orders WHERE status='sent' AND updated_at>=datetime('now',?)",(f'-{int(hours)} hours',)).fetchone();return float(r[0] or 0),int(r[1] or 0)
 def recent_payout_destinations(self,hours=24):
  with self._c() as c:return c.execute("SELECT crypto_address,currency FROM orders WHERE status='sent' AND updated_at>=datetime('now',?)",(f'-{int(hours)} hours',)).fetchall()
class PostgresOpsStore:
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn)
 def get_flag(self,key):
  with self._c() as c,c.cursor() as q:q.execute("SELECT value FROM system_flags WHERE key=%s",(key,));r=q.fetchone();return r[0] if r else None
 def set_flags(self,values):
  with self._c() as c:
   for key,value in values.items():c.execute("INSERT INTO system_flags(key,value,updated_at) VALUES(%s,%s,now()) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=now()",(key,str(value)))
  return True
 def audit(self,*,event,details):
  with self._c() as c:c.execute("INSERT INTO audit_log(event,details) VALUES(%s,%s)",(event,details))
 def cleanup_audit(self,days=90):
  with self._c() as c,c.cursor() as q:q.execute("DELETE FROM audit_log WHERE created_at<now()-(%s*interval '1 day')",(int(days),));return q.rowcount
 def payout_totals(self,hours):
  with self._c() as c,c.cursor() as q:q.execute("SELECT COALESCE(SUM(rub_amount),0),COUNT(*) FROM orders WHERE status='sent' AND updated_at>=now()-(%s*interval '1 hour')",(int(hours),));r=q.fetchone();return float(r[0] or 0),int(r[1] or 0)
 def recent_payout_destinations(self,hours=24):
  with self._c() as c,c.cursor() as q:q.execute("SELECT crypto_address,currency FROM orders WHERE status='sent' AND updated_at>=now()-(%s*interval '1 hour')",(int(hours),));return q.fetchall()
def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteOpsStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('OPS_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_ops_store_not_enabled')
 return PostgresOpsStore(url)
