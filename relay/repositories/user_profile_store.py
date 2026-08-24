"""Bot user identity, immutable referral attribution and referral address."""
from __future__ import annotations
import os
from core import db_runtime

class SQLiteUserProfileStore:
 def __init__(self,path:str,*,timeout:float=10):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def upsert_user(self,*,user_id:int,username,first_name,last_name):
  with self._c() as c:c.execute("INSERT INTO bot_users(user_id,username,first_name,last_name,last_seen) VALUES(?,?,?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_name=excluded.last_name,last_seen=CURRENT_TIMESTAMP",(user_id,username,first_name,last_name));c.commit()
 def claim_referrer(self,*,referred_id:int,referrer_id:int):
  if referred_id==referrer_id:return False
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');exists=c.execute("SELECT 1 FROM referrals WHERE referred_id=? LIMIT 1",(referred_id,)).fetchone()
   if exists:return False
   c.execute("INSERT INTO referrals(referrer_id,referred_id) VALUES(?,?)",(referrer_id,referred_id));c.commit();return True
 def set_referral_address(self,*,user_id:int,currency:str,address:str):
  with self._c() as c:c.execute("INSERT INTO referral_addresses(user_id,currency,address) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET currency=excluded.currency,address=excluded.address",(user_id,currency,address));c.commit()
 def referral_address(self,*,user_id:int,currency:str):
  with self._c() as c:
   row=c.execute("SELECT address FROM referral_addresses WHERE user_id=? AND currency=?",(user_id,currency)).fetchone();return row[0] if row else None

class PostgresUserProfileStore:
 def __init__(self,dsn:str,*,use_b5_acl_functions:bool=False):
  self.dsn=dsn
  self.use_b5_acl_functions=bool(use_b5_acl_functions)
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn)
 def upsert_user(self,*,user_id:int,username,first_name,last_name):
  with self._c() as c:
   if self.use_b5_acl_functions:
    c.execute("SELECT public.bot_b5_upsert_user(%s,%s,%s,%s)",(user_id,username,first_name,last_name))
   else:
    c.execute("INSERT INTO bot_users(user_id,username,first_name,last_name,last_seen) VALUES(%s,%s,%s,%s,now()) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,first_name=excluded.first_name,last_name=excluded.last_name,last_seen=now()",(user_id,username,first_name,last_name))
 def claim_referrer(self,*,referred_id:int,referrer_id:int):
  if referred_id==referrer_id:return False
  with self._c() as c:
   if self.use_b5_acl_functions:
    return bool(c.execute("SELECT public.bot_b5_claim_referrer(%s,%s)",(referred_id,referrer_id)).fetchone()[0])
   with c.cursor() as q:q.execute("INSERT INTO referrals(referrer_id,referred_id) VALUES(%s,%s) ON CONFLICT(referred_id) DO NOTHING",(referrer_id,referred_id));return q.rowcount==1
 def set_referral_address(self,*,user_id:int,currency:str,address:str):
  with self._c() as c:c.execute("INSERT INTO referral_addresses(user_id,currency,address) VALUES(%s,%s,%s) ON CONFLICT(user_id) DO UPDATE SET currency=excluded.currency,address=excluded.address",(user_id,currency,address))
 def referral_address(self,*,user_id:int,currency:str):
  with self._c() as c,c.cursor() as q:q.execute("SELECT address FROM referral_addresses WHERE user_id=%s AND currency=%s",(user_id,currency));row=q.fetchone();return row[0] if row else None

def from_environment(*,sqlite_path:str):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteUserProfileStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('USER_PROFILE_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_user_profile_store_not_enabled')
 return PostgresUserProfileStore(url,use_b5_acl_functions=os.getenv('BOT_B5_ACL_ADAPTER_ENABLED','').lower() in {'1','true','yes'})
