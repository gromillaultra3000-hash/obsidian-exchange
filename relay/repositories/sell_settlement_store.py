"""Atomic Vertu sell settlement, VIP ledger credit and customer outbox."""
from __future__ import annotations
import os,sqlite3
from datetime import datetime,timezone
from decimal import Decimal
from core import db_runtime

_OUTBOX_COLUMNS="id,sell_id,recipient_id,rub_amount,state,attempts,created_at,claimed_at,sent_at,updated_at"
_CLAIM_COLUMNS="id,sell_id,recipient_id,rub_amount,attempts"

def _item(row):
 if row is None:return None
 d=dict(row)
 for k,v in tuple(d.items()):
  if isinstance(v,Decimal):d[k]=float(v)
  elif isinstance(v,datetime):
   if v.tzinfo is None:v=v.replace(tzinfo=timezone.utc)
   d[k]=v.astimezone(timezone.utc).isoformat()
 return d

def _ref(value):
 value=str(value or '').strip()
 if not value or len(value)>255:raise ValueError('invalid_vertu_payout_ref')
 return value

class SQLiteSellSettlementStore:
 def __init__(self,path:str,*,timeout:float=10):
  self.path,self.timeout=path,timeout
 def _c(self):
  c=db_runtime.sqlite_connect(self.path,timeout=self.timeout);c.row_factory=sqlite3.Row;return c
 def settle_vertu(self,sell_id:int,*,payout_ref:str):
  sid,ref=int(sell_id),_ref(payout_ref)
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE')
   row=c.execute("SELECT user_id,rub_amount,status,payout_provider,payout_ref,payout_status FROM sell_orders WHERE id=?",(sid,)).fetchone()
   if not row:c.rollback();return {'action':'missing','sell_id':sid}
   if c.execute("SELECT 1 FROM sell_settlement_ledger WHERE sell_id=?",(sid,)).fetchone():
    c.rollback();return {'action':'already_settled','sell_id':sid}
   if row['status']!='paying':c.rollback();return {'action':'status_conflict','sell_id':sid,'status':row['status']}
   if row['payout_provider']!='vertu' or str(row['payout_ref'] or '')!=ref or str(row['payout_status'] or '').lower()!='paid':
    c.rollback();return {'action':'evidence_conflict','sell_id':sid}
   user_id,rub=int(row['user_id']),row['rub_amount']
   if user_id<=0 or float(rub or 0)<=0:c.rollback();return {'action':'invalid_ledger_data','sell_id':sid}
   changed=c.execute("UPDATE sell_orders SET status='paid',updated_at=CURRENT_TIMESTAMP WHERE id=? AND status='paying' AND payout_provider='vertu' AND payout_ref=? AND lower(payout_status)='paid'",(sid,ref)).rowcount
   if changed!=1:raise RuntimeError('sell_settlement_transition_lost')
   c.execute("INSERT INTO sell_settlement_ledger(sell_id,user_id,rub_amount,payout_provider,payout_ref,payout_status) VALUES(?,?,?,'vertu',?,'paid')",(sid,user_id,rub,ref))
   c.execute("INSERT INTO user_vip_volume(user_id,total_rub,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET total_rub=total_rub+excluded.total_rub,updated_at=CURRENT_TIMESTAMP",(user_id,rub))
   c.execute("INSERT INTO sell_settlement_outbox(sell_id,recipient_id,rub_amount) VALUES(?,?,?)",(sid,user_id,rub))
   c.commit();return {'action':'settled','sell_id':sid,'user_id':user_id,'rub_amount':float(rub),'payout_ref':ref}
 def claim_notification(self):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');row=c.execute("SELECT id FROM sell_settlement_outbox WHERE state='pending' ORDER BY id LIMIT 1").fetchone()
   if not row:c.commit();return None
   ident=int(row['id']);changed=c.execute("UPDATE sell_settlement_outbox SET state='sending',attempts=attempts+1,claimed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='pending'",(ident,)).rowcount
   if changed!=1:raise RuntimeError('sell_settlement_outbox_claim_lost')
   item=c.execute(f"SELECT {_CLAIM_COLUMNS} FROM sell_settlement_outbox WHERE id=?",(ident,)).fetchone();c.commit();return _item(item)
 def mark_notification_sent(self,ident:int)->bool:return self._outbox_state(ident,True)
 def retry_notification(self,ident:int)->bool:return self._outbox_state(ident,False)
 def _outbox_state(self,ident:int,sent:bool)->bool:
  with self._c() as c:
   if sent:q=c.execute("UPDATE sell_settlement_outbox SET state='sent',sent_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='sending'",(int(ident),))
   else:q=c.execute("UPDATE sell_settlement_outbox SET state='pending',claimed_at=NULL,updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='sending'",(int(ident),))
   c.commit();return q.rowcount==1

class PostgresSellSettlementStore(SQLiteSellSettlementStore):
 def __init__(self,dsn:str):self.dsn=dsn
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn,row_factory=psycopg.rows.dict_row)
 def settle_vertu(self,sell_id:int,*,payout_ref:str):
  sid,ref=int(sell_id),_ref(payout_ref)
  with self._c() as c:
   row=c.execute("SELECT user_id,rub_amount,status,payout_provider,payout_ref,payout_status FROM sell_orders WHERE id=%s FOR UPDATE",(sid,)).fetchone()
   if not row:return {'action':'missing','sell_id':sid}
   if c.execute("SELECT 1 FROM sell_settlement_ledger WHERE sell_id=%s",(sid,)).fetchone():return {'action':'already_settled','sell_id':sid}
   if row['status']!='paying':return {'action':'status_conflict','sell_id':sid,'status':row['status']}
   if row['payout_provider']!='vertu' or str(row['payout_ref'] or '')!=ref or str(row['payout_status'] or '').lower()!='paid':return {'action':'evidence_conflict','sell_id':sid}
   user_id,rub=int(row['user_id']),row['rub_amount']
   if user_id<=0 or rub is None or rub<=0:return {'action':'invalid_ledger_data','sell_id':sid}
   changed=c.execute("UPDATE sell_orders SET status='paid',updated_at=now() WHERE id=%s AND status='paying' AND payout_provider='vertu' AND payout_ref=%s AND lower(payout_status)='paid'",(sid,ref)).rowcount
   if changed!=1:raise RuntimeError('sell_settlement_transition_lost')
   c.execute("INSERT INTO sell_settlement_ledger(sell_id,user_id,rub_amount,payout_provider,payout_ref,payout_status) VALUES(%s,%s,%s,'vertu',%s,'paid')",(sid,user_id,rub,ref))
   c.execute("INSERT INTO user_vip_volume(user_id,total_rub,updated_at) VALUES(%s,%s,now()) ON CONFLICT(user_id) DO UPDATE SET total_rub=user_vip_volume.total_rub+excluded.total_rub,updated_at=now()",(user_id,rub))
   c.execute("INSERT INTO sell_settlement_outbox(sell_id,recipient_id,rub_amount) VALUES(%s,%s,%s)",(sid,user_id,rub))
   return {'action':'settled','sell_id':sid,'user_id':user_id,'rub_amount':float(rub),'payout_ref':ref}
 def claim_notification(self):
  with self._c() as c:
   row=c.execute("SELECT id FROM sell_settlement_outbox WHERE state='pending' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
   if not row:return None
   item=c.execute("UPDATE sell_settlement_outbox SET state='sending',attempts=attempts+1,claimed_at=now(),updated_at=now() WHERE id=%s AND state='pending' RETURNING "+_CLAIM_COLUMNS,(row['id'],)).fetchone()
   if not item:raise RuntimeError('sell_settlement_outbox_claim_lost')
   return _item(item)
 def _outbox_state(self,ident:int,sent:bool)->bool:
  with self._c() as c:
   if sent:q=c.execute("UPDATE sell_settlement_outbox SET state='sent',sent_at=now(),updated_at=now() WHERE id=%s AND state='sending'",(int(ident),))
   else:q=c.execute("UPDATE sell_settlement_outbox SET state='pending',claimed_at=NULL,updated_at=now() WHERE id=%s AND state='sending'",(int(ident),))
   return q.rowcount==1

def from_environment(*,sqlite_path:str):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteSellSettlementStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('SELL_SETTLEMENT_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_sell_settlement_store_not_enabled')
 return PostgresSellSettlementStore(url)
