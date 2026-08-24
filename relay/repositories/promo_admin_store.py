"""Promo creation and atomic one-shot win-back issuance."""
from __future__ import annotations
import os
from datetime import datetime,timedelta,timezone
from core import db_runtime
class PromoConflict(RuntimeError):pass
class SQLitePromoAdminStore:
 def __init__(self,path:str,*,timeout:float=10):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def create(self,*,code,discount,max_uses,valid_until):
  import sqlite3
  try:
   with self._c() as c:q=c.execute("INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until) VALUES(?,?,?,?)",(code,discount,max_uses,valid_until));c.commit();return int(q.lastrowid)
  except sqlite3.IntegrityError as e:raise PromoConflict('promo_conflict') from e
 def issue_winback(self,*,order_id,code,discount,valid_hours):
  import sqlite3
  until=(datetime.now(timezone.utc)+timedelta(hours=valid_hours)).strftime('%Y-%m-%d %H:%M:%S')
  try:
   with self._c() as c:
    c.execute('BEGIN IMMEDIATE');claimed=c.execute("INSERT OR IGNORE INTO sent_notifications(order_id,event) VALUES(?,'winback_promo')",(order_id,)).rowcount
    if claimed!=1:return None
    q=c.execute("INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until,is_active) VALUES(?,?,1,?,1)",(code,discount,until));pid=int(q.lastrowid);c.commit();return pid
  except sqlite3.IntegrityError as e:raise PromoConflict('promo_conflict') from e
 def validate_for_user(self,*,code,user_id):
  with self._c() as c:
   row=c.execute("SELECT id,discount_percent,max_uses,uses_count FROM promo_codes WHERE code=? COLLATE NOCASE AND is_active=1 AND valid_until>=datetime('now')",(str(code),)).fetchone()
   if not row or row[3]>=row[2]:return None
   if c.execute("SELECT 1 FROM promo_uses WHERE code_id=? AND user_id=?",(row[0],int(user_id))).fetchone():return None
  return {'code_id':int(row[0]),'discount':float(row[1])}
 def active(self,limit=20):
  with self._c() as c:return c.execute("SELECT code,discount_percent,uses_count,max_uses,valid_until FROM promo_codes WHERE is_active=1 ORDER BY id DESC LIMIT ?",(min(100,max(1,int(limit))),)).fetchall()
class PostgresPromoAdminStore:
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn)
 def create(self,*,code,discount,max_uses,valid_until):
  import psycopg
  try:
   with self._c() as c,c.cursor() as q:q.execute("INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until) VALUES(%s,%s,%s,%s) RETURNING id",(code,discount,max_uses,valid_until));return int(q.fetchone()[0])
  except psycopg.errors.UniqueViolation as e:raise PromoConflict('promo_conflict') from e
 def issue_winback(self,*,order_id,code,discount,valid_hours):
  import psycopg
  try:
   with self._c() as c,c.cursor() as q:
    q.execute("INSERT INTO sent_notifications(order_id,event) VALUES(%s,'winback_promo') ON CONFLICT DO NOTHING",(order_id,))
    if q.rowcount!=1:return None
    q.execute("INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until,is_active) VALUES(%s,%s,1,now()+(%s*interval '1 hour'),true) RETURNING id",(code,discount,valid_hours));return int(q.fetchone()[0])
  except psycopg.errors.UniqueViolation as e:raise PromoConflict('promo_conflict') from e
 def validate_for_user(self,*,code,user_id):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT id,discount_percent,max_uses,uses_count FROM promo_codes WHERE lower(code)=lower(%s) AND is_active=true AND valid_until>=now()",(str(code),));row=q.fetchone()
   if not row or row[3]>=row[2]:return None
   q.execute("SELECT 1 FROM promo_uses WHERE code_id=%s AND user_id=%s",(row[0],int(user_id)))
   if q.fetchone():return None
  return {'code_id':int(row[0]),'discount':float(row[1])}
 def active(self,limit=20):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT code,discount_percent,uses_count,max_uses,valid_until FROM promo_codes WHERE is_active=true ORDER BY id DESC LIMIT %s",(min(100,max(1,int(limit))),));rows=q.fetchall()
  return [(r[0],float(r[1]),r[2],r[3],str(r[4])) for r in rows]
def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLitePromoAdminStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('PROMO_ADMIN_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_promo_admin_store_not_enabled')
 return PostgresPromoAdminStore(url)
