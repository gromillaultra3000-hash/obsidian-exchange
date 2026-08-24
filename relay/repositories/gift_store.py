"""Atomic gift voucher issue and single-winner redemption."""
from __future__ import annotations
import os
from core import db_runtime

class GiftCodeConflict(RuntimeError): pass

class SQLiteGiftStore:
 def __init__(self,path:str,*,timeout:float=10): self.path,self.timeout=path,timeout
 def _connect(self): return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def issue(self,*,sender_id:int,currency:str,rub_amount:float,code:str,destination:str,
           agreed_rate:float,agreed_crypto_amount:float):
  import sqlite3
  try:
   with self._connect() as c:
    c.execute("BEGIN IMMEDIATE")
    cur=c.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,"
      "agreed_rate,agreed_crypto_amount,agreed_at) VALUES(?,?,?,?,?,'pending',?,?,CURRENT_TIMESTAMP)",
      (sender_id,f"gift_{code}",currency,rub_amount,destination,agreed_rate,agreed_crypto_amount))
    oid=int(cur.lastrowid)
    cur=c.execute("INSERT INTO gift_vouchers(sender_id,currency,rub_amount,code,order_id) VALUES(?,?,?,?,?)",
                  (sender_id,currency,rub_amount,code,oid)); gid=int(cur.lastrowid);c.commit()
    return {"order_id":oid,"gift_id":gid}
  except sqlite3.IntegrityError as e: raise GiftCodeConflict("gift_code_conflict") from e
 def get_by_code(self,code:str):
  with self._connect() as c: row=c.execute("SELECT id,currency,rub_amount,status,sender_id FROM gift_vouchers WHERE code=?",(code,)).fetchone()
  return dict(zip(("id","currency","rub_amount","status","sender_id"),row)) if row else None
 def code_exists(self,code:str):
  with self._connect() as c:return c.execute("SELECT 1 FROM gift_vouchers WHERE code=?",(code,)).fetchone() is not None
 def card(self,gift_id:int):
  with self._connect() as c:return c.execute("SELECT currency,rub_amount,code FROM gift_vouchers WHERE id=?",(gift_id,)).fetchone()
 def redeem(self,*,gift_id:int,recipient_id:int,destination:str,agreed_rate:float,agreed_crypto_amount:float):
  with self._connect() as c:
   c.execute("BEGIN IMMEDIATE")
   row=c.execute("SELECT currency,rub_amount,sender_id,status FROM gift_vouchers WHERE id=?",(gift_id,)).fetchone()
   if not row:return {"action":"missing"}
   if row[3]!="paid":return {"action":"not_redeemable","status":row[3]}
   if int(row[2])==int(recipient_id):return {"action":"own_gift"}
   changed=c.execute("UPDATE gift_vouchers SET status='redeemed',recipient_id=?,recipient_address=?,claimed_at=CURRENT_TIMESTAMP WHERE id=? AND status='paid'",(recipient_id,destination,gift_id)).rowcount
   if changed!=1:return {"action":"lost_race"}
   cur=c.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,agreed_rate,agreed_crypto_amount,agreed_at) VALUES(?,?,?,?,?,'paid',?,?,CURRENT_TIMESTAMP)",(recipient_id,f"gift_redeem_{gift_id}",row[0],row[1],destination,agreed_rate,agreed_crypto_amount))
   oid=int(cur.lastrowid);c.commit();return {"action":"redeemed","order_id":oid}

class PostgresGiftStore:
 def __init__(self,dsn:str):self.dsn=dsn
 def _connect(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def issue(self,**d):
  import psycopg
  try:
   with self._connect() as c,c.cursor() as q:
    q.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,agreed_rate,agreed_crypto_amount,agreed_at) VALUES(%s,%s,%s,%s,%s,'pending',%s,%s,now()) RETURNING order_id",(d["sender_id"],f'gift_{d["code"]}',d["currency"],d["rub_amount"],d["destination"],d["agreed_rate"],d["agreed_crypto_amount"]));oid=q.fetchone()["order_id"]
    q.execute("INSERT INTO gift_vouchers(sender_id,currency,rub_amount,code,order_id) VALUES(%s,%s,%s,%s,%s) RETURNING id",(d["sender_id"],d["currency"],d["rub_amount"],d["code"],oid));return {"order_id":oid,"gift_id":q.fetchone()["id"]}
  except psycopg.errors.UniqueViolation as e:raise GiftCodeConflict("gift_code_conflict") from e
 def get_by_code(self,code):
  with self._connect() as c,c.cursor() as q:q.execute("SELECT id,currency,rub_amount,status,sender_id FROM gift_vouchers WHERE code=%s",(code,));r=q.fetchone();return dict(r) if r else None
 def code_exists(self,code):
  with self._connect() as c,c.cursor() as q:q.execute("SELECT 1 FROM gift_vouchers WHERE code=%s",(code,));return q.fetchone() is not None
 def card(self,gift_id):
  with self._connect() as c,c.cursor() as q:
   q.execute("SELECT currency,rub_amount,code FROM gift_vouchers WHERE id=%s",(gift_id,));r=q.fetchone()
   return (r['currency'],r['rub_amount'],r['code']) if r else None
 def redeem(self,**d):
  with self._connect() as c,c.cursor() as q:
   q.execute("SELECT currency,rub_amount,sender_id,status FROM gift_vouchers WHERE id=%s FOR UPDATE",(d["gift_id"],));r=q.fetchone()
   if not r:return {"action":"missing"}
   if r["status"]!="paid":return {"action":"not_redeemable","status":r["status"]}
   if int(r["sender_id"])==int(d["recipient_id"]):return {"action":"own_gift"}
   q.execute("UPDATE gift_vouchers SET status='redeemed',recipient_id=%s,recipient_address=%s,claimed_at=now() WHERE id=%s AND status='paid'",(d["recipient_id"],d["destination"],d["gift_id"]))
   if q.rowcount!=1:return {"action":"lost_race"}
   q.execute("INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,agreed_rate,agreed_crypto_amount,agreed_at) VALUES(%s,%s,%s,%s,%s,'paid',%s,%s,now()) RETURNING order_id",(d["recipient_id"],f'gift_redeem_{d["gift_id"]}',r["currency"],r["rub_amount"],d["destination"],d["agreed_rate"],d["agreed_crypto_amount"]));return {"action":"redeemed","order_id":q.fetchone()["order_id"]}

def from_environment(*,sqlite_path:str):
 url=os.getenv("DATABASE_URL","").strip()
 if not url:return SQLiteGiftStore(sqlite_path)
 if db_runtime.backend(url)!="postgresql" or os.getenv("GIFT_POSTGRES_ENABLED","").lower() not in {"1","true","yes"}:raise RuntimeError("postgres_gift_store_not_enabled")
 return PostgresGiftStore(url)
