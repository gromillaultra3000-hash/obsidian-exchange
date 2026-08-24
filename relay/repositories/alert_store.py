"""Durable atomic alert throttles and monotonic high-water marks."""
from __future__ import annotations
import os
from core import db_runtime
class SQLiteAlertStore:
 def __init__(self,path:str,*,timeout:float=5):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def should_send(self,key,seconds):
  with self._c() as c:c.execute("INSERT OR IGNORE INTO alert_throttle(key,last_sent) VALUES(?,datetime('now','-100 years'))",(key,));q=c.execute("UPDATE alert_throttle SET last_sent=datetime('now') WHERE key=? AND last_sent<=datetime('now',?)",(key,f'-{int(seconds)} seconds'));c.commit();return q.rowcount>0
 def cleanup(self,days):
  with self._c() as c:q=c.execute("DELETE FROM alert_throttle WHERE last_sent<datetime('now',?)",(f'-{int(days)} days',));c.commit();return q.rowcount
 def high_water(self,key,value):
  with self._c() as c:c.execute("INSERT OR IGNORE INTO alert_watermark(key,value) VALUES(?,-1)",(key,));q=c.execute("UPDATE alert_watermark SET value=? WHERE key=? AND value<?",(value,key,value));c.commit();return q.rowcount>0
class PostgresAlertStore:
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn)
 def should_send(self,key,seconds):
  with self._c() as c,c.cursor() as q:q.execute("INSERT INTO alert_throttle(key,last_sent) VALUES(%s,now()-interval '100 years') ON CONFLICT DO NOTHING",(key,));q.execute("UPDATE alert_throttle SET last_sent=now() WHERE key=%s AND last_sent<=now()-(%s*interval '1 second')",(key,int(seconds)));return q.rowcount>0
 def cleanup(self,days):
  with self._c() as c,c.cursor() as q:q.execute("DELETE FROM alert_throttle WHERE last_sent<now()-(%s*interval '1 day')",(int(days),));return q.rowcount
 def high_water(self,key,value):
  with self._c() as c,c.cursor() as q:q.execute("INSERT INTO alert_watermark(key,value) VALUES(%s,-1) ON CONFLICT DO NOTHING",(key,));q.execute("UPDATE alert_watermark SET value=%s WHERE key=%s AND value<%s",(value,key,value));return q.rowcount>0
def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteAlertStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('ALERT_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_alert_store_not_enabled')
 return PostgresAlertStore(url)
