"""Atomic provider health state and rolling attempt journal."""
from __future__ import annotations
import os
from datetime import datetime,timedelta
from core import db_runtime
class SQLiteProviderHealthStore:
 def __init__(self,path:str,*,timeout:float=5):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def record(self,*,provider,success,response_time,max_fails,status,blocker):
  now=datetime.now().isoformat();cut=(datetime.now()-timedelta(hours=2)).isoformat()
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT avg_response_time,failed_count FROM provider_health WHERE provider=?",(provider,)).fetchone()
   if r:
    avg=round((r[0] or 0)*.8+response_time*.2,3);fails=0 if success else (r[1] or 0)+1;healthy=1 if success or fails<max_fails else 0;c.execute("UPDATE provider_health SET avg_response_time=?,failed_count=?,last_checked=?,is_healthy=?,status=?,blocker=? WHERE provider=?",(avg,fails,now,healthy,status,blocker,provider))
   else:c.execute("INSERT INTO provider_health(provider,avg_response_time,failed_count,last_checked,is_healthy,status,blocker) VALUES(?,?,?,?,?,?,?)",(provider,round(response_time,3),0 if success else 1,now,1 if success else 0,status,blocker))
   c.execute("INSERT INTO provider_attempts(provider,ts,success) VALUES(?,?,?)",(provider,now,1 if success else 0));c.execute("DELETE FROM provider_attempts WHERE ts<?",(cut,));c.commit()
 def attempt_stats(self,provider,since):
  with self._c() as c:r=c.execute("SELECT COUNT(*) n,COALESCE(SUM(success),0) ok FROM provider_attempts WHERE provider=? AND ts>=?",(provider,since)).fetchone();return {'count':int(r[0]),'success':int(r[1])}
 def all_health(self):
  with self._c() as c:c.row_factory=__import__('sqlite3').Row;return [dict(r) for r in c.execute('SELECT * FROM provider_health').fetchall()]
 def reset(self,provider):
  with self._c() as c:q=c.execute("UPDATE provider_health SET failed_count=0,is_healthy=1,status='READY',blocker='' WHERE provider=?",(provider,));c.commit();return q.rowcount==1
class PostgresProviderHealthStore:
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def record(self,*,provider,success,response_time,max_fails,status,blocker):
  with self._c() as c,c.cursor() as q:
   q.execute('SELECT avg_response_time,failed_count FROM provider_health WHERE provider=%s FOR UPDATE',(provider,));r=q.fetchone()
   if r:
    avg=round(float(r['avg_response_time'] or 0)*.8+response_time*.2,3);fails=0 if success else int(r['failed_count'] or 0)+1;healthy=success or fails<max_fails;q.execute("UPDATE provider_health SET avg_response_time=%s,failed_count=%s,last_checked=now(),is_healthy=%s,status=%s,blocker=%s WHERE provider=%s",(avg,fails,healthy,status,blocker,provider))
   else:q.execute("INSERT INTO provider_health(provider,avg_response_time,failed_count,last_checked,is_healthy,status,blocker) VALUES(%s,%s,%s,now(),%s,%s,%s)",(provider,response_time,0 if success else 1,success,status,blocker))
   q.execute("INSERT INTO provider_attempts(provider,ts,success) VALUES(%s,now(),%s)",(provider,success));q.execute("DELETE FROM provider_attempts WHERE ts<now()-interval '2 hours'")
 def attempt_stats(self,provider,since):
  with self._c() as c,c.cursor() as q:q.execute("SELECT COUNT(*) n,COALESCE(SUM(success::int),0) ok FROM provider_attempts WHERE provider=%s AND ts>=%s",(provider,since));r=q.fetchone();return {'count':int(r['n']),'success':int(r['ok'])}
 def all_health(self):
  with self._c() as c,c.cursor() as q:
   q.execute('SELECT * FROM provider_health');rows=[]
   for r in q.fetchall():
    d=dict(r)
    if d.get('last_checked') is not None:d['last_checked']=d['last_checked'].replace(tzinfo=None).isoformat()
    rows.append(d)
   return rows
 def reset(self,provider):
  with self._c() as c,c.cursor() as q:q.execute("UPDATE provider_health SET failed_count=0,is_healthy=true,status='READY',blocker='' WHERE provider=%s",(provider,));return q.rowcount==1
def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteProviderHealthStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('PROVIDER_HEALTH_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_provider_health_store_not_enabled')
 return PostgresProviderHealthStore(url)
