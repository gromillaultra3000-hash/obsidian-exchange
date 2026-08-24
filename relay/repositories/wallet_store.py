"""Verified wallet links and pre-sign wallet-send intents."""
from __future__ import annotations
import os
from core import db_runtime
class SQLiteWalletStore:
 def __init__(self,path:str,*,timeout:float=5):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def remember_link(self,*,user_id,chain,address,verified_at):
  with self._c() as c:c.execute("INSERT INTO wallet_links(user_id,chain,address,verified_at) VALUES(?,?,?,?) ON CONFLICT(user_id,chain) DO UPDATE SET address=excluded.address,verified_at=excluded.verified_at",(user_id,chain,address,verified_at));c.commit()
 def forget_links(self,*,user_id,chain=None):
  with self._c() as c:q=c.execute("DELETE FROM wallet_links WHERE user_id=?"+(" AND chain=?" if chain else ""),((user_id,chain) if chain else (user_id,)));c.commit();return q.rowcount
 def links_for(self,user_id):
  with self._c() as c:r=c.execute("SELECT chain,address,verified_at FROM wallet_links WHERE user_id=? ORDER BY chain",(user_id,)).fetchall();return [{'chain':x[0],'address':x[1],'verified_at':x[2]} for x in r]
 def remember_intent(self,*,user_id,chain,sell_id,from_address,to_address,amount,marker,created_at):
  with self._c() as c:q=c.execute("INSERT INTO wallet_send_intents(user_id,chain,sell_id,from_address,to_address,amount,marker,created_at) VALUES(?,?,?,?,?,?,?,?)",(user_id,chain,sell_id,from_address,to_address,amount,marker,created_at));c.commit();return int(q.lastrowid)
 def mark_signed(self,*,user_id,sell_id,signed_at):
  with self._c() as c:q=c.execute("UPDATE wallet_send_intents SET signed_at=? WHERE user_id=? AND sell_id=? AND signed_at IS NULL",(signed_at,user_id,sell_id));c.commit();return q.rowcount>0
 def intents_for(self,sell_id):
  with self._c() as c:r=c.execute("SELECT from_address,marker,created_at,signed_at FROM wallet_send_intents WHERE sell_id=? ORDER BY id",(sell_id,)).fetchall();return [{'from_address':x[0],'marker':x[1],'created_at':x[2],'signed_at':x[3]} for x in r]
class PostgresWalletStore:
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def remember_link(self,*,user_id,chain,address,verified_at):
  with self._c() as c:c.execute("INSERT INTO wallet_links(user_id,chain,address,verified_at) VALUES(%s,%s,%s,%s) ON CONFLICT(user_id,chain) DO UPDATE SET address=excluded.address,verified_at=excluded.verified_at",(user_id,chain,address,verified_at))
 def forget_links(self,*,user_id,chain=None):
  with self._c() as c,c.cursor() as q:q.execute("DELETE FROM wallet_links WHERE user_id=%s"+(" AND chain=%s" if chain else ""),((user_id,chain) if chain else (user_id,)));return q.rowcount
 def links_for(self,user_id):
  with self._c() as c,c.cursor() as q:q.execute("SELECT chain,address,verified_at FROM wallet_links WHERE user_id=%s ORDER BY chain",(user_id,));return [dict(x) for x in q.fetchall()]
 def remember_intent(self,*,user_id,chain,sell_id,from_address,to_address,amount,marker,created_at):
  with self._c() as c,c.cursor() as q:q.execute("INSERT INTO wallet_send_intents(user_id,chain,sell_id,from_address,to_address,amount,marker,created_at) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",(user_id,chain,sell_id,from_address,to_address,amount,marker,created_at));return int(q.fetchone()['id'])
 def mark_signed(self,*,user_id,sell_id,signed_at):
  with self._c() as c,c.cursor() as q:q.execute("UPDATE wallet_send_intents SET signed_at=%s WHERE user_id=%s AND sell_id=%s AND signed_at IS NULL",(signed_at,user_id,sell_id));return q.rowcount>0
 def intents_for(self,sell_id):
  with self._c() as c,c.cursor() as q:q.execute("SELECT from_address,marker,created_at,signed_at FROM wallet_send_intents WHERE sell_id=%s ORDER BY id",(sell_id,));return [dict(x) for x in q.fetchall()]
def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteWalletStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('WALLET_STORE_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_wallet_store_not_enabled')
 return PostgresWalletStore(url)
