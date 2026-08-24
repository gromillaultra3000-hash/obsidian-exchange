"""Administrative access lists, anti-fraud blocks and curated reserves."""
from __future__ import annotations
import os
from core import db_runtime

class SQLiteAdminConfigStore:
 def __init__(self,path:str,*,timeout:float=10):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def set_staff(self,*,role:str,user_id:int,username,added_by:int):
  table=_staff_table(role)
  with self._c() as c:c.execute(f"INSERT INTO {table}(user_id,username,added_by) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET is_active=1,username=excluded.username",(user_id,username,added_by));c.commit()
 def deactivate_staff(self,*,role:str,user_id:int):
  table=_staff_table(role)
  with self._c() as c:q=c.execute(f"UPDATE {table} SET is_active=0 WHERE user_id=? AND is_active=1",(user_id,));c.commit();return q.rowcount==1
 def active_staff_ids(self,*,role:str):
  table=_staff_table(role)
  with self._c() as c:return {int(r[0]) for r in c.execute(f"SELECT user_id FROM {table} WHERE is_active=1").fetchall()}
 def staff_rows(self,*,role:str):
  table=_staff_table(role)
  with self._c() as c:return c.execute(f"SELECT user_id,username,added_at,is_active FROM {table} ORDER BY added_at DESC").fetchall()
 def is_user_blocked(self,user_id:int):
  with self._c() as c:return c.execute("SELECT 1 FROM blocked_users WHERE user_id=?",(user_id,)).fetchone() is not None
 def blocked_address_rows(self,*,limit:int=20):
  with self._c() as c:return c.execute("SELECT address,reason,created_at FROM blocked_addresses ORDER BY created_at DESC LIMIT ?",(int(limit),)).fetchall()
 def blocked_user_rows(self,*,limit:int=50):
  with self._c() as c:return c.execute("SELECT user_id,reason,blocked_at FROM blocked_users ORDER BY blocked_at DESC LIMIT ?",(min(100,max(1,int(limit))),)).fetchall()
 def block_user(self,*,user_id:int,reason:str='admin block'):
  with self._c() as c:q=c.execute("INSERT OR IGNORE INTO blocked_users(user_id,reason) VALUES(?,?)",(user_id,reason));c.commit();return q.rowcount==1
 def unblock_user(self,user_id:int):
  with self._c() as c:q=c.execute("DELETE FROM blocked_users WHERE user_id=?",(user_id,));c.commit();return q.rowcount==1
 def block_address(self,*,address:str,reason:str,blocked_by:int):
  with self._c() as c:c.execute("INSERT INTO blocked_addresses(address,reason,blocked_by) VALUES(?,?,?) ON CONFLICT(address) DO UPDATE SET reason=excluded.reason,blocked_by=excluded.blocked_by",(address,reason,blocked_by));c.commit()
 def unblock_addresses(self,addresses):
  values=tuple(dict.fromkeys(addresses))
  if not values:return 0
  with self._c() as c:q=c.execute("DELETE FROM blocked_addresses WHERE address IN (%s)"%','.join('?'*len(values)),values);c.commit();return q.rowcount
 def set_reserve(self,*,currency:str,amount:float):
  with self._c() as c:c.execute("INSERT INTO reserves(currency,amount,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(currency) DO UPDATE SET amount=excluded.amount,updated_at=CURRENT_TIMESTAMP",(currency,amount));c.commit()

class PostgresAdminConfigStore(SQLiteAdminConfigStore):
 def __init__(self,dsn:str):self.dsn=dsn
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn)
 def set_staff(self,*,role:str,user_id:int,username,added_by:int):
  table=_staff_table(role)
  with self._c() as c:c.execute(f"INSERT INTO {table}(user_id,username,added_by) VALUES(%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET is_active=true,username=excluded.username",(user_id,username,added_by))
 def deactivate_staff(self,*,role:str,user_id:int):
  table=_staff_table(role)
  return self._update(f"UPDATE {table} SET is_active=false WHERE user_id=%s AND is_active=true",(user_id,))
 def active_staff_ids(self,*,role:str):
  table=_staff_table(role)
  with self._c() as c:return {int(r[0]) for r in c.execute(f"SELECT user_id FROM {table} WHERE is_active=true").fetchall()}
 def staff_rows(self,*,role:str):
  table=_staff_table(role)
  with self._c() as c:
   rows=c.execute(f"SELECT user_id,username,added_at,is_active FROM {table} ORDER BY added_at DESC").fetchall()
   return [(r[0],r[1],r[2].isoformat() if hasattr(r[2],'isoformat') else str(r[2]),r[3]) for r in rows]
 def is_user_blocked(self,user_id:int):
  with self._c() as c:return c.execute("SELECT 1 FROM blocked_users WHERE user_id=%s",(user_id,)).fetchone() is not None
 def blocked_address_rows(self,*,limit:int=20):
  with self._c() as c:
   rows=c.execute("SELECT address,reason,created_at FROM blocked_addresses ORDER BY created_at DESC LIMIT %s",(int(limit),)).fetchall()
   return [(r[0],r[1],r[2].isoformat()) for r in rows]
 def blocked_user_rows(self,*,limit:int=50):
  with self._c() as c:
   rows=c.execute("SELECT user_id,reason,blocked_at FROM blocked_users ORDER BY blocked_at DESC LIMIT %s",(min(100,max(1,int(limit))),)).fetchall()
   return [(r[0],r[1],r[2].isoformat() if hasattr(r[2],'isoformat') else str(r[2])) for r in rows]
 def block_user(self,*,user_id:int,reason:str='admin block'):return self._update("INSERT INTO blocked_users(user_id,reason) VALUES(%s,%s) ON CONFLICT(user_id) DO NOTHING",(user_id,reason))
 def unblock_user(self,user_id:int):return self._update("DELETE FROM blocked_users WHERE user_id=%s",(user_id,))
 def block_address(self,*,address:str,reason:str,blocked_by:int):
  with self._c() as c:c.execute("INSERT INTO blocked_addresses(address,reason,blocked_by) VALUES(%s,%s,%s) ON CONFLICT(address) DO UPDATE SET reason=excluded.reason,blocked_by=excluded.blocked_by",(address,reason,blocked_by))
 def unblock_addresses(self,addresses):
  values=list(dict.fromkeys(addresses))
  if not values:return 0
  with self._c() as c,c.cursor() as q:q.execute("DELETE FROM blocked_addresses WHERE address=ANY(%s)",(values,));return q.rowcount
 def set_reserve(self,*,currency:str,amount:float):
  with self._c() as c:c.execute("INSERT INTO reserves(currency,amount,updated_at) VALUES(%s,%s,now()) ON CONFLICT(currency) DO UPDATE SET amount=excluded.amount,updated_at=now()",(currency,amount))
 def _update(self,sql,args):
  with self._c() as c,c.cursor() as q:q.execute(sql,args);return q.rowcount==1

def _staff_table(role:str):
 if role not in {'worker','operator'}:raise ValueError('invalid_staff_role')
 return role+'s'
def from_environment(*,sqlite_path:str):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteAdminConfigStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('ADMIN_CONFIG_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_admin_config_store_not_enabled')
 return PostgresAdminConfigStore(url)
