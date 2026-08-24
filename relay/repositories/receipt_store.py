"""Receipt metadata, delivery marker and single-winner dispute claim."""
from __future__ import annotations
import os
from core import db_runtime
class SQLiteReceiptStore:
 def __init__(self,path:str,*,timeout:float=5):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def record(self,*,order_id,path,filename,content_type,sha256):
  with self._c() as c:
   c.execute("INSERT INTO order_receipts(order_id,path,filename,content_type,sha256) VALUES(?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET path=excluded.path,filename=excluded.filename,content_type=excluded.content_type,sha256=excluded.sha256,created_at=CURRENT_TIMESTAMP,dispute_opened_at=NULL",(order_id,path,filename,content_type,sha256));c.commit()
 def get(self,order_id):
  with self._c() as c:r=c.execute("SELECT path,filename,content_type FROM order_receipts WHERE order_id=?",(order_id,)).fetchone();return {'path':r[0],'filename':r[1],'content_type':r[2]} if r else None
 def state(self,order_id):
  with self._c() as c:r=c.execute("SELECT o.receipt_sent_at FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE r.order_id=? LIMIT 1",(int(order_id),)).fetchone()
  if not r:return ''
  return 'sent' if str(r[0] or '').strip() else 'stored'
 def authorized_state(self,order_id,*,user_id=None,session_token=None):
  uid=int(user_id) if user_id is not None else None;token=str(session_token or '').strip()
  if uid is not None and uid<=0:raise ValueError('invalid_order_authority_user')
  if len(token)>256:raise ValueError('invalid_order_authority_token')
  if uid is None and not token:raise ValueError('missing_order_authority')
  with self._c() as c:r=c.execute("SELECT o.receipt_sent_at FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE r.order_id=? AND (o.user_id=? OR EXISTS(SELECT 1 FROM payment_sessions ps WHERE ps.order_id=o.order_id AND ps.session_token=?)) LIMIT 1",(int(order_id),uid,token or None)).fetchone()
  if not r:return ''
  return 'sent' if str(r[0] or '').strip() else 'stored'
 def duplicates(self,*,order_id,sha256):
  with self._c() as c:return [r[0] for r in c.execute("SELECT order_id FROM order_receipts WHERE sha256=? AND order_id<>? ORDER BY order_id LIMIT 5",(sha256,order_id)).fetchall()]
 def mark_sent(self,order_id):
  with self._c() as c:q=c.execute("UPDATE orders SET receipt_sent_at=CURRENT_TIMESTAMP WHERE order_id=? AND receipt_sent_at IS NULL",(order_id,));c.commit();return q.rowcount==1
 def candidates(self,delay_min):
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row;r=c.execute("SELECT r.order_id,r.created_at receipt_at,o.status,o.rub_amount,o.user_id,o.username FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE r.dispute_opened_at IS NULL AND o.status NOT IN('paid','sent','cancelled') AND r.created_at<=datetime('now',?) AND r.created_at>=datetime('now','-2 days') ORDER BY r.order_id",(f'-{int(delay_min)} minutes',)).fetchall();return [dict(x) for x in r]
 def claim_dispute(self,order_id):
  with self._c() as c:q=c.execute("UPDATE order_receipts SET dispute_opened_at=CURRENT_TIMESTAMP WHERE order_id=? AND dispute_opened_at IS NULL",(order_id,));c.commit();return q.rowcount==1
 def sessions(self,order_id):
  with self._c() as c:
   c.row_factory=__import__('sqlite3').Row;return [dict(r) for r in c.execute("SELECT provider,provider_invoice_id,provider_payload,status FROM payment_sessions WHERE order_id=? ORDER BY id DESC",(order_id,)).fetchall()]
 def order_guard_fields(self,order_id):
  with self._c() as c:r=c.execute("SELECT rub_amount,verification_requested FROM orders WHERE order_id=?",(order_id,)).fetchone();return {'rub_amount':r[0],'verification_requested':r[1]} if r else None
 def fraud_profile(self,order_id):
  with self._c() as c:
   r=c.execute("SELECT user_id FROM orders WHERE order_id=?",(order_id,)).fetchone()
   if not r or not r[0] or r[0]<=0:return {'user_id':None,'expired':0,'paid':0}
   s=c.execute("SELECT SUM(status='expired'),SUM(status IN ('paid','sent')) FROM orders WHERE user_id=?",(r[0],)).fetchone();return {'user_id':r[0],'expired':int(s[0] or 0),'paid':int(s[1] or 0)}
class PostgresReceiptStore:
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def record(self,*,order_id,path,filename,content_type,sha256):
  with self._c() as c:c.execute("INSERT INTO order_receipts(order_id,path,filename,content_type,sha256) VALUES(%s,%s,%s,%s,%s) ON CONFLICT(order_id) DO UPDATE SET path=excluded.path,filename=excluded.filename,content_type=excluded.content_type,sha256=excluded.sha256,created_at=now(),dispute_opened_at=NULL",(order_id,path,filename,content_type,sha256))
 def get(self,order_id):
  with self._c() as c,c.cursor() as q:q.execute("SELECT path,filename,content_type FROM order_receipts WHERE order_id=%s",(order_id,));r=q.fetchone();return dict(r) if r else None
 def state(self,order_id):
  with self._c() as c,c.cursor() as q:q.execute("SELECT o.receipt_sent_at FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE r.order_id=%s LIMIT 1",(int(order_id),));r=q.fetchone()
  if not r:return ''
  return 'sent' if r['receipt_sent_at'] else 'stored'
 def authorized_state(self,order_id,*,user_id=None,session_token=None):
  uid=int(user_id) if user_id is not None else None;token=str(session_token or '').strip()
  if uid is not None and uid<=0:raise ValueError('invalid_order_authority_user')
  if len(token)>256:raise ValueError('invalid_order_authority_token')
  if uid is None and not token:raise ValueError('missing_order_authority')
  with self._c() as c,c.cursor() as q:
   if os.getenv('RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED','').lower() in {'1','true','yes'}:q.execute("SELECT public.relay_receipt_authorized_state(%s::bigint,%s::bigint,%s::text) AS state",(int(order_id),uid,token or None));return str(q.fetchone()['state'] or '')
   q.execute("SELECT o.receipt_sent_at FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE r.order_id=%s AND (o.user_id=%s OR EXISTS(SELECT 1 FROM payment_sessions ps WHERE ps.order_id=o.order_id AND ps.session_token=%s)) LIMIT 1",(int(order_id),uid,token or None));r=q.fetchone()
  if not r:return ''
  return 'sent' if r['receipt_sent_at'] else 'stored'
 def duplicates(self,*,order_id,sha256):
  with self._c() as c,c.cursor() as q:q.execute("SELECT order_id FROM order_receipts WHERE sha256=%s AND order_id<>%s ORDER BY order_id LIMIT 5",(sha256,order_id));return [r['order_id'] for r in q.fetchall()]
 def mark_sent(self,order_id):return self._update("UPDATE orders SET receipt_sent_at=now() WHERE order_id=%s AND receipt_sent_at IS NULL",(order_id,))
 def candidates(self,delay_min):
  with self._c() as c,c.cursor() as q:q.execute("SELECT r.order_id,r.created_at receipt_at,o.status,o.rub_amount,o.user_id,o.username FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE r.dispute_opened_at IS NULL AND o.status NOT IN('paid','sent','cancelled') AND r.created_at<=now()-(%s*interval '1 minute') AND r.created_at>=now()-interval '2 days' ORDER BY r.order_id",(int(delay_min),));return [dict(x) for x in q.fetchall()]
 def claim_dispute(self,order_id):return self._update("UPDATE order_receipts SET dispute_opened_at=now() WHERE order_id=%s AND dispute_opened_at IS NULL",(order_id,))
 def sessions(self,order_id):
  with self._c() as c,c.cursor() as q:q.execute("SELECT provider,provider_invoice_id,provider_payload,status FROM payment_sessions WHERE order_id=%s ORDER BY id DESC",(order_id,));return [dict(r) for r in q.fetchall()]
 def order_guard_fields(self,order_id):
  with self._c() as c,c.cursor() as q:q.execute("SELECT rub_amount,verification_requested FROM orders WHERE order_id=%s",(order_id,));r=q.fetchone();return dict(r) if r else None
 def fraud_profile(self,order_id):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT user_id FROM orders WHERE order_id=%s",(order_id,));r=q.fetchone()
   if not r or not r['user_id'] or r['user_id']<=0:return {'user_id':None,'expired':0,'paid':0}
   q.execute("SELECT COUNT(*) FILTER(WHERE status='expired') expired,COUNT(*) FILTER(WHERE status IN ('paid','sent')) paid FROM orders WHERE user_id=%s",(r['user_id'],));s=q.fetchone();return {'user_id':r['user_id'],'expired':int(s['expired']),'paid':int(s['paid'])}
 def _update(self,sql,args):
  with self._c() as c,c.cursor() as q:q.execute(sql,args);return q.rowcount==1
def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteReceiptStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('RECEIPT_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_receipt_store_not_enabled')
 return PostgresReceiptStore(url)
