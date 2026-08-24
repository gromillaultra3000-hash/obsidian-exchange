"""Swap-session creation and compare-and-set status persistence."""
from __future__ import annotations
import os
from core import db_runtime

class SQLiteSwapStore:
 def __init__(self,path:str,*,timeout:float=5):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def create(self,*,token,user_id,coin_from,coin_to,amount_from,address_to,external_id,external_url,status,provider,deposit_address,web_user_id=None):
  with self._c() as c:q=c.execute("INSERT INTO swap_sessions(session_token,user_id,coin_from,coin_to,amount_from,address_to,trocador_id,trocador_url,status,web_user_id,provider,deposit_address) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",(token,user_id,coin_from,coin_to,amount_from,address_to,external_id,external_url,status,web_user_id,provider,deposit_address));c.commit();return int(q.lastrowid)
 def transition(self,*,token,expected_status,new_status):
  if new_status==expected_status:return True
  with self._c() as c:q=c.execute("UPDATE swap_sessions SET status=?,updated_at=CURRENT_TIMESTAMP WHERE session_token=? AND status=?",(new_status,token,expected_status));c.commit();return q.rowcount==1
 def swaps_for_web_user(self,*,web_user_id,user_id,limit=20):
  with self._c() as c:
   rows=c.execute("SELECT session_token,coin_from,coin_to,amount_from,status,created_at FROM swap_sessions WHERE web_user_id=? OR (? IS NOT NULL AND user_id=?) ORDER BY created_at DESC,id DESC LIMIT ?",(web_user_id,user_id,user_id,min(100,max(1,int(limit))))).fetchall()
  keys=('token','coin_from','coin_to','amount_from','status','created_at');return [dict(zip(keys,r)) for r in rows]
 def get_by_token(self,token):
  value=str(token or '').strip();return self._lookup('session_token',value) if value and len(value)<=256 else None
 def get_by_external_id(self,external_id):
  value=str(external_id or '').strip();return self._lookup('trocador_id',value) if value and len(value)<=256 else None
 def _lookup(self,column,value):
  with self._c() as c:r=c.execute(f"SELECT session_token,user_id,coin_from,coin_to,amount_from,address_to,trocador_id,trocador_url,status,provider,deposit_address FROM swap_sessions WHERE {column}=?",(value,)).fetchone()
  keys=('session_token','user_id','coin_from','coin_to','amount_from','address_to','external_id','external_url','status','provider','deposit_address');return dict(zip(keys,r)) if r else None
 def unfinished(self,final_statuses):
  values=tuple(final_statuses)
  if not values:return []
  if len(values)>32:raise ValueError('too_many_final_statuses')
  with self._c() as c:return c.execute("SELECT session_token,user_id,trocador_id,coin_from,coin_to,status,provider,amount_from FROM swap_sessions WHERE status NOT IN (%s) ORDER BY id LIMIT 500"%','.join('?'*len(values)),values).fetchall()

class PostgresSwapStore:
 def __init__(self,dsn:str):self.dsn=dsn
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn)
 def create(self,*,token,user_id,coin_from,coin_to,amount_from,address_to,external_id,external_url,status,provider,deposit_address,web_user_id=None):
  with self._c() as c,c.cursor() as q:q.execute("INSERT INTO swap_sessions(session_token,user_id,coin_from,coin_to,amount_from,address_to,trocador_id,trocador_url,status,web_user_id,provider,deposit_address) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",(token,user_id,coin_from,coin_to,amount_from,address_to,external_id,external_url,status,web_user_id,provider,deposit_address));return int(q.fetchone()[0])
 def transition(self,*,token,expected_status,new_status):
  if new_status==expected_status:return True
  with self._c() as c,c.cursor() as q:q.execute("UPDATE swap_sessions SET status=%s,updated_at=now() WHERE session_token=%s AND status=%s",(new_status,token,expected_status));return q.rowcount==1
 def swaps_for_web_user(self,*,web_user_id,user_id,limit=20):
  from psycopg.rows import dict_row
  with self._c() as c,c.cursor(row_factory=dict_row) as q:
   if user_id is None:
    q.execute("SELECT session_token AS token,coin_from,coin_to,amount_from,status,created_at FROM swap_sessions WHERE web_user_id=%s ORDER BY created_at DESC,id DESC LIMIT %s",(web_user_id,min(100,max(1,int(limit)))))
   else:
    q.execute("SELECT session_token AS token,coin_from,coin_to,amount_from,status,created_at FROM swap_sessions WHERE web_user_id=%s OR user_id=%s ORDER BY created_at DESC,id DESC LIMIT %s",(web_user_id,user_id,min(100,max(1,int(limit)))))
   return [dict(r) for r in q.fetchall()]
 def get_by_token(self,token):
  value=str(token or '').strip();return self._lookup('session_token',value) if value and len(value)<=256 else None
 def get_by_external_id(self,external_id):
  value=str(external_id or '').strip();return self._lookup('trocador_id',value) if value and len(value)<=256 else None
 def _lookup(self,column,value):
  from psycopg.rows import dict_row
  with self._c() as c,c.cursor(row_factory=dict_row) as q:q.execute(f"SELECT session_token,user_id,coin_from,coin_to,amount_from,address_to,trocador_id AS external_id,trocador_url AS external_url,status,provider,deposit_address FROM swap_sessions WHERE {column}=%s",(value,));r=q.fetchone();return dict(r) if r else None
 def unfinished(self,final_statuses):
  values=list(final_statuses)
  if not values:return []
  if len(values)>32:raise ValueError('too_many_final_statuses')
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT session_token,user_id,trocador_id,coin_from,coin_to,status,provider,amount_from FROM swap_sessions WHERE NOT (status=ANY(%s)) ORDER BY id LIMIT 500",(values,))
   return [(r[0],r[1],r[2],r[3],r[4],r[5],r[6],float(r[7]) if r[7] is not None else None) for r in q.fetchall()]

def from_environment(*,sqlite_path:str):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteSwapStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('SWAP_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_swap_store_not_enabled')
 return PostgresSwapStore(url)
