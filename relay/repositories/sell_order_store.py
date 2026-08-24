"""Sell-order creation and fail-closed RUB payout lifecycle."""
from __future__ import annotations
import os
from core import db_runtime

class SQLiteSellOrderStore:
 def __init__(self,path:str,*,timeout:float=10):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def create(self,**d):
  with self._c() as c:q=c.execute("INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,status,payout_method,payout_bank,payout_details,payout_name) VALUES(?,?,?,?,?,?,'pending',?,?,?,?)",(d['user_id'],d['currency'],d['crypto_amount'],d['rub_amount'],d['sbp_phone'],d['receive_address'],d['payout_method'],d['payout_bank'],d['payout_details'],d['payout_name']));c.commit();return int(q.lastrowid)
 def get(self,sell_id:int):
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row;r=c.execute("SELECT * FROM sell_orders WHERE id=?",(sell_id,)).fetchone();return dict(r) if r else None
 def vertu_payout_by_ref(self,ref:str):
  value=str(ref or '').strip()
  if not value or len(value)>256:return None
  suffix=value.split('_')[-1]
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row
   r=c.execute("SELECT id,user_id,rub_amount,payout_status FROM sell_orders WHERE payout_provider='vertu' AND payout_ref=? LIMIT 1",(value,)).fetchone()
   if r:return dict(r)
   rows=c.execute("SELECT id,user_id,rub_amount,payout_status FROM sell_orders WHERE payout_provider='vertu' AND payout_ref=? ORDER BY id LIMIT 2",(suffix,)).fetchall()
   return dict(rows[0]) if len(rows)==1 else None
 def active_vertu_payouts(self,terminal_statuses,*,newer_than_days:int=3):
  done=tuple(str(x).lower() for x in terminal_statuses)
  if not done:raise ValueError('terminal_payout_statuses_required')
  days=min(30,max(1,int(newer_than_days)))
  holes=','.join('?' for _ in done)
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row
   rows=c.execute("SELECT id,user_id,rub_amount,payout_ref,payout_status FROM sell_orders WHERE payout_provider='vertu' AND payout_ref IS NOT NULL AND payout_ref!=''"+f" AND (payout_status IS NULL OR lower(payout_status) NOT IN ({holes}))"+" AND datetime(updated_at)>datetime('now',?) ORDER BY id LIMIT 100",done+(f'-{days} days',)).fetchall()
   return [dict(x) for x in rows]
 def pending_for_user(self,*,user_id:int,currency:str,limit:int=10):
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row;r=c.execute("SELECT id,currency,crypto_amount,rub_amount,receive_address,created_at FROM sell_orders WHERE user_id=? AND status='pending' AND currency=? ORDER BY id DESC LIMIT ?",(user_id,currency,limit)).fetchall();return [dict(x) for x in r]
 def sells_for_user(self,*,user_id:int,limit:int=20):
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row;r=c.execute("SELECT id,currency,crypto_amount,rub_amount,sbp_phone,status,created_at,payout_method,payout_details,payout_bank FROM sell_orders WHERE user_id=? ORDER BY created_at DESC,id DESC LIMIT ?",(user_id,min(100,max(0,int(limit))))).fetchall();return [dict(x) for x in r]
 def pending_view_for_user(self,*,user_id:int,status:str,limit:int=10):
  if status!='pending':raise ValueError('pending_sell_status_required')
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row;r=c.execute("SELECT id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,created_at,payout_method,payout_details,payout_bank FROM sell_orders WHERE user_id=? AND status=? ORDER BY id DESC LIMIT ?",(user_id,status,min(100,max(0,int(limit))))).fetchall();return [dict(x) for x in r]
 def deposit_snapshot(self,sell_id:int):
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row
   r=c.execute("SELECT currency,crypto_amount,receive_address,status,tx_hash,created_at FROM sell_orders WHERE id=?",(sell_id,)).fetchone()
   if not r:return None
   used=c.execute("SELECT tx_hash FROM sell_orders WHERE tx_hash IS NOT NULL AND tx_hash!='' AND id!=?",(sell_id,)).fetchall()
   return {'order':dict(r),'claimed_txids':{x[0] for x in used}}
 def reserve_txid(self,*,sell_id:int,txid:str,expected_status:str):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE')
   q=c.execute("UPDATE sell_orders SET tx_hash=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status=? AND (tx_hash IS NULL OR tx_hash='' OR tx_hash=?) AND NOT EXISTS(SELECT 1 FROM sell_orders other WHERE other.id!=? AND other.tx_hash=?)",(txid,sell_id,expected_status,txid,sell_id,txid));c.commit();return q.rowcount==1
 def stale_unreferenced(self,minutes:int):
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row;r=c.execute("SELECT id,user_id,rub_amount,updated_at FROM sell_orders WHERE status='paying' AND (payout_ref IS NULL OR payout_ref='') AND datetime(updated_at)<datetime('now',?)",(f'-{int(minutes)} minutes',)).fetchall();return [dict(x) for x in r]
 def claim(self,sell_id:int):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');changed=c.execute("UPDATE sell_orders SET status='paying',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status NOT IN('paid','paying')",(sell_id,)).rowcount;r=c.execute("SELECT user_id,rub_amount,status FROM sell_orders WHERE id=?",(sell_id,)).fetchone();c.commit()
  return None if not r else {'claimed':changed==1,'user_id':r[0],'rub_amount':r[1],'status':r[2]}
 def cancel_pending(self,sell_id:int):return self._cas(sell_id,"pending","cancelled")
 def release(self,sell_id:int):return self._cas(sell_id,"paying","pending")
 def reject(self,sell_id:int):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT user_id FROM sell_orders WHERE id=?",(sell_id,)).fetchone()
   if not r:return None
   changed=c.execute("UPDATE sell_orders SET status='rejected',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status NOT IN('paid','paying')",(sell_id,)).rowcount;c.commit();return {'user_id':r[0],'changed':changed==1}
 def record_provider(self,sell_id:int,*,provider:str,ref:str,status:str):
  with self._c() as c:q=c.execute("UPDATE sell_orders SET payout_provider=?,payout_ref=?,payout_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status!='paid'",(provider,ref,status,sell_id));c.commit();return q.rowcount==1
 def mark_manual_or_processing(self,sell_id:int,*,settled:bool,provider:str):
  return self._cas(sell_id,'paying','paid' if settled else 'paying',extra=('payout_provider',provider))
 def mark_settled(self,sell_id:int):
  with self._c() as c:q=c.execute("UPDATE sell_orders SET status='paid',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='paying'",(sell_id,));c.commit();return q.rowcount==1
 def mark_rejected(self,sell_id:int):return self.release(sell_id)
 def release_unreferenced(self,sell_id:int):
  with self._c() as c:q=c.execute("UPDATE sell_orders SET status='pending',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='paying' AND (payout_ref IS NULL OR payout_ref='')",(sell_id,));c.commit();return q.rowcount==1
 def update_payout_status(self,sell_id:int,status:str):
  with self._c() as c:q=c.execute("UPDATE sell_orders SET payout_status=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND status!='paid'",(status,sell_id));c.commit();return q.rowcount==1
 def _cas(self,sell_id,old,new,extra=None):
  assignment="status=?,updated_at=CURRENT_TIMESTAMP";args=[new]
  if extra:assignment+=f",{extra[0]}=?";args.append(extra[1])
  args.extend((sell_id,old))
  with self._c() as c:q=c.execute(f"UPDATE sell_orders SET {assignment} WHERE id=? AND status=?",args);c.commit();return q.rowcount==1

class PostgresSellOrderStore(SQLiteSellOrderStore):
 def __init__(self,dsn:str):self.dsn=dsn
 def _c(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def create(self,**d):
  with self._c() as c,c.cursor() as q:q.execute("INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,status,payout_method,payout_bank,payout_details,payout_name) VALUES(%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s) RETURNING id",(d['user_id'],d['currency'],d['crypto_amount'],d['rub_amount'],d['sbp_phone'],d['receive_address'],d['payout_method'],d['payout_bank'],d['payout_details'],d['payout_name']));return int(q.fetchone()['id'])
 def get(self,sell_id:int):
  with self._c() as c:r=c.execute("SELECT * FROM sell_orders WHERE id=%s",(sell_id,)).fetchone();return dict(r) if r else None
 def vertu_payout_by_ref(self,ref:str):
  value=str(ref or '').strip()
  if not value or len(value)>256:return None
  suffix=value.split('_')[-1]
  with self._c() as c:
   r=c.execute("SELECT id,user_id,rub_amount,payout_status FROM sell_orders WHERE payout_provider='vertu' AND payout_ref=%s LIMIT 1",(value,)).fetchone()
   if r:return dict(r)
   rows=c.execute("SELECT id,user_id,rub_amount,payout_status FROM sell_orders WHERE payout_provider='vertu' AND payout_ref=%s ORDER BY id LIMIT 2",(suffix,)).fetchall()
   return dict(rows[0]) if len(rows)==1 else None
 def active_vertu_payouts(self,terminal_statuses,*,newer_than_days:int=3):
  done=[str(x).lower() for x in terminal_statuses]
  if not done:raise ValueError('terminal_payout_statuses_required')
  days=min(30,max(1,int(newer_than_days)))
  with self._c() as c:return [dict(x) for x in c.execute("SELECT id,user_id,rub_amount,payout_ref,payout_status FROM sell_orders WHERE payout_provider='vertu' AND COALESCE(payout_ref,'')!='' AND (payout_status IS NULL OR lower(payout_status)<>ALL(%s)) AND updated_at>now()-(%s*interval '1 day') ORDER BY id LIMIT 100",(done,days)).fetchall()]
 def pending_for_user(self,*,user_id:int,currency:str,limit:int=10):
  with self._c() as c:return [dict(x) for x in c.execute("SELECT id,currency,crypto_amount,rub_amount,receive_address,created_at FROM sell_orders WHERE user_id=%s AND status='pending' AND currency=%s ORDER BY id DESC LIMIT %s",(user_id,currency,limit)).fetchall()]
 def sells_for_user(self,*,user_id:int,limit:int=20):
  with self._c() as c:return [dict(x) for x in c.execute("SELECT id,currency,crypto_amount,rub_amount,sbp_phone,status,created_at,payout_method,payout_details,payout_bank FROM sell_orders WHERE user_id=%s ORDER BY created_at DESC,id DESC LIMIT %s",(user_id,min(100,max(0,int(limit))))).fetchall()]
 def pending_view_for_user(self,*,user_id:int,status:str,limit:int=10):
  if status!='pending':raise ValueError('pending_sell_status_required')
  with self._c() as c:return [dict(x) for x in c.execute("SELECT id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,created_at,payout_method,payout_details,payout_bank FROM sell_orders WHERE user_id=%s AND status=%s ORDER BY id DESC LIMIT %s",(user_id,status,min(100,max(0,int(limit))))).fetchall()]
 def deposit_snapshot(self,sell_id:int):
  with self._c() as c:
   r=c.execute("SELECT currency,crypto_amount,receive_address,status,tx_hash,created_at FROM sell_orders WHERE id=%s",(sell_id,)).fetchone()
   if not r:return None
   used=c.execute("SELECT tx_hash FROM sell_orders WHERE tx_hash IS NOT NULL AND tx_hash!='' AND id!=%s",(sell_id,)).fetchall()
   return {'order':dict(r),'claimed_txids':{x['tx_hash'] for x in used}}
 def reserve_txid(self,*,sell_id:int,txid:str,expected_status:str):
  with self._c() as c:
   c.execute("SELECT pg_advisory_xact_lock(hashtext('sell_orders.tx_hash'))")
   q=c.execute("UPDATE sell_orders SET tx_hash=%s,updated_at=now() WHERE id=%s AND status=%s AND COALESCE(tx_hash,'') IN ('',%s) AND NOT EXISTS(SELECT 1 FROM sell_orders other WHERE other.id!=%s AND other.tx_hash=%s)",(txid,sell_id,expected_status,txid,sell_id,txid));return q.rowcount==1
 def stale_unreferenced(self,minutes:int):
  with self._c() as c:return [dict(x) for x in c.execute("SELECT id,user_id,rub_amount,updated_at FROM sell_orders WHERE status='paying' AND COALESCE(payout_ref,'')='' AND updated_at<now()-(%s*interval '1 minute')",(int(minutes),)).fetchall()]
 def claim(self,sell_id:int):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT user_id,rub_amount,status FROM sell_orders WHERE id=%s FOR UPDATE",(sell_id,));r=q.fetchone()
   if not r:return None
   changed=False
   if r['status'] not in ('paid','paying'):q.execute("UPDATE sell_orders SET status='paying',updated_at=now() WHERE id=%s AND status=%s",(sell_id,r['status']));changed=q.rowcount==1
   return {'claimed':changed,'user_id':r['user_id'],'rub_amount':r['rub_amount'],'status':'paying' if changed else r['status']}
 def reject(self,sell_id:int):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT user_id,status FROM sell_orders WHERE id=%s FOR UPDATE",(sell_id,));r=q.fetchone()
   if not r:return None
   q.execute("UPDATE sell_orders SET status='rejected',updated_at=now() WHERE id=%s AND status NOT IN('paid','paying')",(sell_id,));return {'user_id':r['user_id'],'changed':q.rowcount==1}
 def record_provider(self,sell_id:int,*,provider:str,ref:str,status:str):return self._update("UPDATE sell_orders SET payout_provider=%s,payout_ref=%s,payout_status=%s,updated_at=now() WHERE id=%s AND status!='paid'",(provider,ref,status,sell_id))
 def mark_manual_or_processing(self,sell_id:int,*,settled:bool,provider:str):return self._update("UPDATE sell_orders SET status=%s,payout_provider=%s,updated_at=now() WHERE id=%s AND status='paying'",('paid' if settled else 'paying',provider,sell_id))
 def mark_settled(self,sell_id:int):return self._update("UPDATE sell_orders SET status='paid',updated_at=now() WHERE id=%s AND status='paying'",(sell_id,))
 def release_unreferenced(self,sell_id:int):return self._update("UPDATE sell_orders SET status='pending',updated_at=now() WHERE id=%s AND status='paying' AND (payout_ref IS NULL OR payout_ref='')",(sell_id,))
 def update_payout_status(self,sell_id:int,status:str):return self._update("UPDATE sell_orders SET payout_status=%s,updated_at=now() WHERE id=%s AND status!='paid'",(status,sell_id))
 def _cas(self,sell_id,old,new,extra=None):
  if extra:return self._update(f"UPDATE sell_orders SET status=%s,updated_at=now(),{extra[0]}=%s WHERE id=%s AND status=%s",(new,extra[1],sell_id,old))
  return self._update("UPDATE sell_orders SET status=%s,updated_at=now() WHERE id=%s AND status=%s",(new,sell_id,old))
 def _update(self,sql,args):
  with self._c() as c,c.cursor() as q:q.execute(sql,args);return q.rowcount==1

def from_environment(*,sqlite_path:str):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteSellOrderStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('SELL_ORDER_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_sell_order_store_not_enabled')
 return PostgresSellOrderStore(url)
