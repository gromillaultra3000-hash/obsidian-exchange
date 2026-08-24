"""Atomic expiry/dead-session transitions with durable external work."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from decimal import Decimal

from core import db_runtime


_ACTIVE_SESSIONS=("invoice_created","awaiting_payment")
_WORK_KINDS=("order_expired_notify","session_dead_admin","session_dead_customer","provider_cancel")
_WORK_COLUMNS=("id,kind,order_id,session_token,provider,provider_invoice_id,user_id,currency,"
               "rub_amount,order_status,has_receipt,detail,state,attempts,created_at,claimed_at,"
               "completed_at,updated_at")
def _value(value):
    if isinstance(value,Decimal): return float(value)
    if isinstance(value,datetime):
        if value.tzinfo is None: value=value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return value


def _work(row):
    if row is None:return None
    result={k:_value(v) for k,v in dict(row).items()}
    result["has_receipt"]=bool(result["has_receipt"])
    return result


class SQLiteOrderLifecycleStore:
    def __init__(self,path:str,*,timeout:float=10):
        self.path,self.timeout=path,timeout
    def _c(self):
        c=db_runtime.sqlite_connect(self.path,timeout=self.timeout);c.row_factory=sqlite3.Row;return c

    def expire_due(self,*,limit:int=100)->int:
        limit=max(1,min(int(limit),1000))
        with self._c() as c:
            c.execute("BEGIN IMMEDIATE")
            rows=c.execute("SELECT o.order_id,o.user_id,o.currency,o.rub_amount FROM orders o "
              "WHERE o.status='pending' AND datetime(o.created_at)<datetime('now','-2 hours') "
              "AND NOT EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) "
              "AND NOT EXISTS(SELECT 1 FROM payment_sessions ps WHERE ps.order_id=o.order_id "
              "AND ps.status IN('invoice_created','awaiting_payment') AND datetime(ps.expires_at)>datetime('now')) "
              "ORDER BY o.order_id LIMIT ?",(limit,)).fetchall()
            count=0
            for row in rows:
                oid=int(row["order_id"])
                changed=c.execute("UPDATE orders SET status='expired',updated_at=CURRENT_TIMESTAMP "
                                  "WHERE order_id=? AND status='pending'",(oid,)).rowcount
                if changed!=1:continue
                count+=1
                if row["user_id"] and int(row["user_id"])>0:
                    c.execute("INSERT OR IGNORE INTO sent_notifications(order_id,event) VALUES(?,'order_expired')",(oid,))
                    if c.execute("SELECT changes()").fetchone()[0]:
                        c.execute("INSERT OR IGNORE INTO order_lifecycle_work"
                          "(kind,order_id,user_id,currency,rub_amount,order_status) "
                          "VALUES('order_expired_notify',?,?,?,?, 'expired')",
                          (oid,int(row["user_id"]),row["currency"],row["rub_amount"]))
                sessions=c.execute("SELECT session_token,provider,provider_invoice_id FROM payment_sessions "
                  "WHERE order_id=? AND provider LIKE 'brabus%' AND provider_invoice_id IS NOT NULL",(oid,)).fetchall()
                for session in sessions:
                    c.execute("INSERT OR IGNORE INTO order_lifecycle_work"
                      "(kind,order_id,session_token,provider,provider_invoice_id,order_status) "
                      "VALUES('provider_cancel',?,?,?,?, 'expired')",
                      (oid,session["session_token"],session["provider"],session["provider_invoice_id"]))
            c.commit();return count

    def fail_session(self,order_id:int,token:str,provider:str,*,detail:str=""):
        oid,token=int(order_id),str(token or "").strip()
        if not token or len(token)>256:raise ValueError("invalid_session_token")
        with self._c() as c:
            c.execute("BEGIN IMMEDIATE")
            changed=c.execute("UPDATE payment_sessions SET status='failed',updated_at=CURRENT_TIMESTAMP "
              "WHERE order_id=? AND session_token=? AND status IN('invoice_created','awaiting_payment')",
              (oid,token)).rowcount
            row=c.execute("SELECT o.user_id,o.rub_amount,o.currency,o.status,"
              "EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) has_receipt "
              "FROM orders o WHERE o.order_id=?",(oid,)).fetchone()
            if changed!=1 or not row:c.rollback();return {"action":"conflict","order_id":oid}
            claimed=c.execute("INSERT OR IGNORE INTO sent_notifications(order_id,event) "
                              "VALUES(?,'session_dead')",(oid,)).rowcount
            if claimed:
                c.execute("INSERT OR IGNORE INTO order_lifecycle_work(kind,order_id,session_token,provider,"
                  "user_id,currency,rub_amount,order_status,has_receipt,detail) "
                  "VALUES('session_dead_admin',?,?,?,?,?,?,?,?,?)",
                  (oid,token,str(provider or "")[:80],row["user_id"],row["currency"],row["rub_amount"],
                   row["status"],int(row["has_receipt"]),str(detail or "")[:500]))
                if row["user_id"] and int(row["user_id"])>0 and row["status"] not in ("paid","sent"):
                    c.execute("INSERT OR IGNORE INTO order_lifecycle_work(kind,order_id,session_token,provider,"
                      "user_id,currency,rub_amount,order_status,has_receipt,detail) "
                      "VALUES('session_dead_customer',?,?,?,?,?,?,?,?,?)",
                      (oid,token,str(provider or "")[:80],row["user_id"],row["currency"],row["rub_amount"],
                       row["status"],int(row["has_receipt"]),str(detail or "")[:500]))
            c.commit();return {"action":"failed","order_id":oid,"claimed":bool(claimed)}

    def claim_work(self,*,kind:str|None=None):
        if kind is not None and kind not in _WORK_KINDS:raise ValueError("invalid_work_kind")
        with self._c() as c:
            c.execute("BEGIN IMMEDIATE")
            if kind is None:row=c.execute("SELECT id FROM order_lifecycle_work WHERE state='pending' ORDER BY id LIMIT 1").fetchone()
            else:row=c.execute("SELECT id FROM order_lifecycle_work WHERE state='pending' AND kind=? ORDER BY id LIMIT 1",(kind,)).fetchone()
            if not row:c.commit();return None
            ident=int(row[0]); changed=c.execute("UPDATE order_lifecycle_work SET state='sending',attempts=attempts+1,"
              "claimed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='pending'",(ident,)).rowcount
            if changed!=1:raise RuntimeError("lifecycle_work_claim_lost")
            item=c.execute(f"SELECT {_WORK_COLUMNS} FROM order_lifecycle_work WHERE id=?",(ident,)).fetchone();c.commit();return _work(item)

    def complete_work(self,ident:int)->bool:
        with self._c() as c:
            changed=c.execute("UPDATE order_lifecycle_work SET state='done',completed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
                              "WHERE id=? AND state='sending'",(int(ident),)).rowcount;c.commit();return changed==1
    def retry_work(self,ident:int)->bool:
        with self._c() as c:
            changed=c.execute("UPDATE order_lifecycle_work SET state='pending',claimed_at=NULL,updated_at=CURRENT_TIMESTAMP "
                              "WHERE id=? AND state='sending'",(int(ident),)).rowcount;c.commit();return changed==1


class PostgresOrderLifecycleStore(SQLiteOrderLifecycleStore):
    def __init__(self,dsn:str):self.dsn=dsn
    def _c(self):
        import psycopg
        return psycopg.connect(self.dsn,row_factory=psycopg.rows.dict_row)
    def expire_due(self,*,limit:int=100)->int:
        limit=max(1,min(int(limit),1000))
        with self._c() as c:
            rows=c.execute("SELECT o.order_id,o.user_id,o.currency,o.rub_amount FROM orders o WHERE o.status='pending' "
              "AND o.created_at<now()-interval '2 hours' AND NOT EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) "
              "AND NOT EXISTS(SELECT 1 FROM payment_sessions ps WHERE ps.order_id=o.order_id AND ps.status=ANY(%s) "
              "AND ps.expires_at>now()) ORDER BY o.order_id FOR UPDATE OF o SKIP LOCKED LIMIT %s",
              (list(_ACTIVE_SESSIONS),limit)).fetchall();count=0
            for row in rows:
                oid=int(row["order_id"]);cur=c.execute("UPDATE orders SET status='expired',updated_at=now() WHERE order_id=%s AND status='pending'",(oid,))
                if cur.rowcount!=1:continue
                count+=1
                if row["user_id"] and int(row["user_id"])>0:
                    marker=c.execute("INSERT INTO sent_notifications(order_id,event) VALUES(%s,'order_expired') ON CONFLICT DO NOTHING RETURNING order_id",(oid,)).fetchone()
                    if marker:c.execute("INSERT INTO order_lifecycle_work(kind,order_id,user_id,currency,rub_amount,order_status) "
                      "VALUES('order_expired_notify',%s,%s,%s,%s,'expired') ON CONFLICT DO NOTHING",
                      (oid,row["user_id"],row["currency"],row["rub_amount"]))
                sessions=c.execute("SELECT session_token,provider,provider_invoice_id FROM payment_sessions WHERE order_id=%s "
                  "AND provider LIKE 'brabus%%' AND provider_invoice_id IS NOT NULL",(oid,)).fetchall()
                for session in sessions:c.execute("INSERT INTO order_lifecycle_work(kind,order_id,session_token,provider,provider_invoice_id,order_status) "
                  "VALUES('provider_cancel',%s,%s,%s,%s,'expired') ON CONFLICT DO NOTHING",
                  (oid,session["session_token"],session["provider"],session["provider_invoice_id"]))
            return count
    def fail_session(self,order_id:int,token:str,provider:str,*,detail:str=""):
        oid,token=int(order_id),str(token or "").strip()
        if not token or len(token)>256:raise ValueError("invalid_session_token")
        with self._c() as c:
            changed=c.execute("UPDATE payment_sessions SET status='failed',updated_at=now() WHERE order_id=%s AND session_token=%s "
              "AND status=ANY(%s)",(oid,token,list(_ACTIVE_SESSIONS))).rowcount
            row=c.execute("SELECT o.user_id,o.rub_amount,o.currency,o.status,EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) has_receipt "
                          "FROM orders o WHERE o.order_id=%s FOR UPDATE",(oid,)).fetchone()
            if changed!=1 or not row:c.rollback();return {"action":"conflict","order_id":oid}
            marker=c.execute("INSERT INTO sent_notifications(order_id,event) VALUES(%s,'session_dead') ON CONFLICT DO NOTHING RETURNING order_id",(oid,)).fetchone()
            if marker:
                values=(oid,token,str(provider or "")[:80],row["user_id"],row["currency"],row["rub_amount"],row["status"],row["has_receipt"],str(detail or "")[:500])
                c.execute("INSERT INTO order_lifecycle_work(kind,order_id,session_token,provider,user_id,currency,rub_amount,order_status,has_receipt,detail) "
                  "VALUES('session_dead_admin',%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",values)
                if row["user_id"] and int(row["user_id"])>0 and row["status"] not in ("paid","sent"):
                    c.execute("INSERT INTO order_lifecycle_work(kind,order_id,session_token,provider,user_id,currency,rub_amount,order_status,has_receipt,detail) "
                      "VALUES('session_dead_customer',%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",values)
            return {"action":"failed","order_id":oid,"claimed":bool(marker)}
    def claim_work(self,*,kind:str|None=None):
        if kind is not None and kind not in _WORK_KINDS:raise ValueError("invalid_work_kind")
        with self._c() as c:
            if kind is None:row=c.execute("SELECT id FROM order_lifecycle_work WHERE state='pending' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1").fetchone()
            else:row=c.execute("SELECT id FROM order_lifecycle_work WHERE state='pending' AND kind=%s ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1",(kind,)).fetchone()
            if not row:return None
            item=c.execute("UPDATE order_lifecycle_work SET state='sending',attempts=attempts+1,claimed_at=now(),updated_at=now() "
                           f"WHERE id=%s AND state='pending' RETURNING {_WORK_COLUMNS}",(row["id"],)).fetchone()
            if not item:raise RuntimeError("lifecycle_work_claim_lost")
            return _work(item)
    def complete_work(self,ident:int)->bool:
        with self._c() as c:return c.execute("UPDATE order_lifecycle_work SET state='done',completed_at=now(),updated_at=now() WHERE id=%s AND state='sending'",(int(ident),)).rowcount==1
    def retry_work(self,ident:int)->bool:
        with self._c() as c:return c.execute("UPDATE order_lifecycle_work SET state='pending',claimed_at=NULL,updated_at=now() WHERE id=%s AND state='sending'",(int(ident),)).rowcount==1


def from_environment(*,sqlite_path:str):
    url=os.getenv("DATABASE_URL","").strip()
    if not url:return SQLiteOrderLifecycleStore(sqlite_path)
    if db_runtime.backend(url)!="postgresql" or os.getenv("ORDER_LIFECYCLE_POSTGRES_ENABLED","").lower() not in {"1","true","yes"}:
        raise RuntimeError("postgres_order_lifecycle_store_not_enabled")
    return PostgresOrderLifecycleStore(url)
