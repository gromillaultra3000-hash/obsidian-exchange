"""Read models used by operational watches, queues, trust and offerings."""
from __future__ import annotations

import os
from datetime import datetime, timedelta

from core import db_runtime


class SQLiteOperationalReadStore:
    def __init__(self, path, *, timeout=5): self.path, self.timeout = path, timeout
    def _c(self):
        c = db_runtime.sqlite_connect(self.path, timeout=self.timeout)
        c.row_factory = __import__('sqlite3').Row
        return c
    def reserves(self):
        with self._c() as c:return [(r[0],r[1]) for r in c.execute("SELECT currency,amount FROM reserves")]
    def paid_deals(self,user_id,statuses):
        with self._c() as c:return int(c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status IN (%s)"%','.join('?'*len(statuses)),(user_id,)+tuple(statuses)).fetchone()[0])
    def client_order_counts(self,user_id,statuses):
        with self._c() as c:
            r=c.execute("SELECT COUNT(*),SUM(CASE WHEN status IN (%s) THEN 1 ELSE 0 END) FROM orders WHERE user_id=?"%','.join('?'*len(statuses)),tuple(statuses)+(user_id,)).fetchone();return {'created':int(r[0] or 0),'paid':int(r[1] or 0)}
    def payout_rows(self,order_id=None):
        sql="SELECT o.order_id,o.user_id,o.username,o.rub_amount,o.currency,o.crypto_address,o.network,o.status,CAST((julianday('now')-julianday(COALESCE(NULLIF(o.updated_at,''),o.created_at)))*24*60 AS INT) age_min FROM orders o WHERE o.status='paid' AND (o.paid_btc_tx IS NULL OR o.paid_btc_tx='')"
        args=()
        if order_id is not None:sql+=' AND o.order_id=?';args=(order_id,)
        with self._c() as c:return [dict(r) for r in c.execute(sql,args).fetchall()]
    def payout_evidence_orders(self,*,min_age_minutes,max_age_days):
        with self._c() as c:return [dict(r) for r in c.execute("SELECT order_id,user_id,rub_amount,currency,network,crypto_address,agreed_crypto_amount,CAST(strftime('%s',COALESCE(updated_at,created_at)) AS INT) paid_ts FROM orders WHERE status='paid' AND (paid_btc_tx IS NULL OR paid_btc_tx='') AND COALESCE(updated_at,created_at)<=datetime('now',?) AND COALESCE(updated_at,created_at)>=datetime('now',?) ORDER BY COALESCE(updated_at,created_at)",(f'-{int(min_age_minutes)} minutes',f'-{int(max_age_days)} days')).fetchall()]
    def payout_evidence_order(self,order_id):
        with self._c() as c:
            r=c.execute("SELECT order_id,user_id,rub_amount,currency,network,crypto_address,agreed_crypto_amount,status,paid_btc_tx,CAST(strftime('%s',COALESCE(updated_at,created_at)) AS INT) paid_ts FROM orders WHERE order_id=?",(int(order_id),)).fetchone();return dict(r) if r else None
    def used_payout_txids(self):
        with self._c() as c:return [r[0] for r in c.execute("SELECT paid_btc_tx FROM orders WHERE paid_btc_tx IS NOT NULL AND paid_btc_tx!=''").fetchall()]
    def chain_reconciliation_orders(self,days):
        with self._c() as c:return [dict(r) for r in c.execute("SELECT order_id,currency,crypto_address,paid_btc_tx,rub_amount,status,created_at,updated_at FROM orders WHERE status IN('sent','paid') AND created_at>=datetime('now',?) ORDER BY order_id DESC",(f'-{int(days)} days',)).fetchall()]
    def receipt_queue_rows(self):
        with self._c() as c:return [dict(r) for r in c.execute("SELECT o.order_id,o.user_id,o.username,o.rub_amount,o.currency,o.crypto_address,o.network,o.status,(o.receipt_sent_at IS NOT NULL AND o.receipt_sent_at<>'') delivered,CAST((julianday('now')-julianday(r.created_at))*24*60 AS INT) age_min FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE o.status NOT IN('paid','sent') AND NOT EXISTS(SELECT 1 FROM sent_notifications sn WHERE sn.order_id=o.order_id AND sn.event='receipt_rejected')").fetchall()]
    def conversion_snapshot(self,*,window_hours,stuck_minutes,undelivered_minutes,unresolved_minutes,unresolved_days):
        win=f'-{int(window_hours)} hours'
        with self._c() as c:
            issued=c.execute("SELECT COUNT(*) FROM payment_sessions WHERE created_at>=datetime('now',?)",(win,)).fetchone()[0]
            paid=c.execute("SELECT COUNT(*) FROM orders WHERE status IN('paid','sent') AND updated_at>=datetime('now',?)",(win,)).fetchone()[0]
            early=c.execute("SELECT COUNT(*) FROM payment_sessions WHERE status='expired' AND created_at>=datetime('now',?) AND expires_at IS NOT NULL AND updated_at IS NOT NULL AND updated_at<expires_at",(win,)).fetchone()[0]
            stuck=[dict(r) for r in c.execute("SELECT order_id,rub_amount,currency,CAST((julianday('now')-julianday(COALESCE(updated_at,created_at)))*24*60 AS INT) age_min FROM orders WHERE status='paid' AND (paid_btc_tx IS NULL OR paid_btc_tx='') AND (updated_at IS NULL OR updated_at<=datetime('now',?)) ORDER BY COALESCE(updated_at,created_at)",(f'-{int(stuck_minutes)} minutes',)).fetchall()]
            try:undelivered=[dict(r) for r in c.execute("SELECT o.order_id,o.rub_amount,o.currency,o.status,COALESCE(ps.provider,'?') provider,CAST((julianday('now')-julianday(r.created_at))*24*60 AS INT) age_min FROM order_receipts r JOIN orders o ON o.order_id=r.order_id LEFT JOIN payment_sessions ps ON ps.id=(SELECT id FROM payment_sessions WHERE order_id=o.order_id ORDER BY id DESC LIMIT 1) WHERE (o.receipt_sent_at IS NULL OR o.receipt_sent_at='') AND o.status NOT IN('sent','cancelled') AND r.created_at<=datetime('now',?) AND r.created_at>=datetime('now','-24 hours') ORDER BY r.created_at",(f'-{int(undelivered_minutes)} minutes',)).fetchall()]
            except __import__('sqlite3').OperationalError:undelivered=[]
            try:unresolved=[dict(r) for r in c.execute("SELECT o.order_id,o.rub_amount,o.currency,o.status,(o.receipt_sent_at IS NOT NULL AND o.receipt_sent_at<>'') delivered,COALESCE(ps.provider,'?') provider,CAST((julianday('now')-julianday(r.created_at))*24*60 AS INT) age_min FROM order_receipts r JOIN orders o ON o.order_id=r.order_id LEFT JOIN payment_sessions ps ON ps.id=(SELECT id FROM payment_sessions WHERE order_id=o.order_id ORDER BY id DESC LIMIT 1) WHERE o.status NOT IN('paid','sent') AND NOT EXISTS(SELECT 1 FROM sent_notifications sn WHERE sn.order_id=o.order_id AND sn.event='receipt_rejected') AND r.created_at<=datetime('now',?) AND r.created_at>=datetime('now',?) ORDER BY r.created_at",(f'-{int(unresolved_minutes)} minutes',f'-{int(unresolved_days)} days')).fetchall()]
            except __import__('sqlite3').OperationalError:unresolved=[]
        return {'issued':int(issued),'paid':int(paid),'early_expiry':int(early),'stuck_payouts':stuck,'undelivered_receipts':undelivered,'unresolved_receipts':unresolved}


class PostgresOperationalReadStore:
    def __init__(self,dsn):self.dsn=dsn
    def _c(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn,row_factory=dict_row)
    def reserves(self):
        with self._c() as c:return [(r['currency'],r['amount']) for r in c.execute("SELECT currency,amount FROM reserves")]
    def paid_deals(self,user_id,statuses):
        with self._c() as c:return int(c.execute("SELECT COUNT(*) FROM orders WHERE user_id=%s AND status=ANY(%s)",(user_id,list(statuses))).fetchone()['count'])
    def client_order_counts(self,user_id,statuses):
        with self._c() as c:
            r=c.execute("SELECT COUNT(*) created,COUNT(*) FILTER(WHERE status=ANY(%s)) paid FROM orders WHERE user_id=%s",(list(statuses),user_id)).fetchone();return {'created':int(r['created']),'paid':int(r['paid'])}
    def payout_rows(self,order_id=None):
        sql="SELECT o.order_id,o.user_id,o.username,o.rub_amount,o.currency,o.crypto_address,o.network,o.status,FLOOR(EXTRACT(EPOCH FROM(now()-COALESCE(o.updated_at,o.created_at)))/60)::int age_min FROM orders o WHERE o.status='paid' AND COALESCE(o.paid_btc_tx,'')=''";args=()
        if order_id is not None:sql+=' AND o.order_id=%s';args=(order_id,)
        with self._c() as c:return [dict(r) for r in c.execute(sql,args).fetchall()]
    def payout_evidence_orders(self,*,min_age_minutes,max_age_days):
        with self._c() as c:return [dict(r) for r in c.execute("SELECT order_id,user_id,rub_amount,currency,network,crypto_address,agreed_crypto_amount,EXTRACT(EPOCH FROM COALESCE(updated_at,created_at))::bigint paid_ts FROM orders WHERE status='paid' AND COALESCE(paid_btc_tx,'')='' AND COALESCE(updated_at,created_at)<=now()-(%s*interval '1 minute') AND COALESCE(updated_at,created_at)>=now()-(%s*interval '1 day') ORDER BY COALESCE(updated_at,created_at)",(int(min_age_minutes),int(max_age_days))).fetchall()]
    def payout_evidence_order(self,order_id):
        with self._c() as c:
            r=c.execute("SELECT order_id,user_id,rub_amount,currency,network,crypto_address,agreed_crypto_amount,status,paid_btc_tx,EXTRACT(EPOCH FROM COALESCE(updated_at,created_at))::bigint paid_ts FROM orders WHERE order_id=%s",(int(order_id),)).fetchone();return dict(r) if r else None
    def used_payout_txids(self):
        with self._c() as c:return [r['paid_btc_tx'] for r in c.execute("SELECT paid_btc_tx FROM orders WHERE paid_btc_tx IS NOT NULL AND paid_btc_tx!=''").fetchall()]
    def chain_reconciliation_orders(self,days):
        with self._c() as c:return [dict(r) for r in c.execute("SELECT order_id,currency,crypto_address,paid_btc_tx,rub_amount,status,created_at,updated_at FROM orders WHERE status IN('sent','paid') AND created_at>=now()-(%s*interval '1 day') ORDER BY order_id DESC",(int(days),)).fetchall()]
    def receipt_queue_rows(self):
        with self._c() as c:return [dict(r) for r in c.execute("SELECT o.order_id,o.user_id,o.username,o.rub_amount,o.currency,o.crypto_address,o.network,o.status,(o.receipt_sent_at IS NOT NULL) delivered,FLOOR(EXTRACT(EPOCH FROM(now()-r.created_at))/60)::int age_min FROM order_receipts r JOIN orders o ON o.order_id=r.order_id WHERE o.status NOT IN('paid','sent') AND NOT EXISTS(SELECT 1 FROM sent_notifications sn WHERE sn.order_id=o.order_id AND sn.event='receipt_rejected')").fetchall()]
    def conversion_snapshot(self,*,window_hours,stuck_minutes,undelivered_minutes,unresolved_minutes,unresolved_days):
        with self._c() as c:
            issued=c.execute("SELECT COUNT(*) FROM payment_sessions WHERE created_at>=now()-(%s*interval '1 hour')",(int(window_hours),)).fetchone()['count']
            paid=c.execute("SELECT COUNT(*) FROM orders WHERE status IN('paid','sent') AND updated_at>=now()-(%s*interval '1 hour')",(int(window_hours),)).fetchone()['count']
            early=c.execute("SELECT COUNT(*) FROM payment_sessions WHERE status='expired' AND created_at>=now()-(%s*interval '1 hour') AND expires_at IS NOT NULL AND updated_at IS NOT NULL AND updated_at<expires_at",(int(window_hours),)).fetchone()['count']
            stuck=[dict(r) for r in c.execute("SELECT order_id,rub_amount,currency,FLOOR(EXTRACT(EPOCH FROM(now()-COALESCE(updated_at,created_at)))/60)::int age_min FROM orders WHERE status='paid' AND COALESCE(paid_btc_tx,'')='' AND (updated_at IS NULL OR updated_at<=now()-(%s*interval '1 minute')) ORDER BY COALESCE(updated_at,created_at)",(int(stuck_minutes),)).fetchall()]
            base=" FROM order_receipts r JOIN orders o ON o.order_id=r.order_id LEFT JOIN LATERAL(SELECT provider FROM payment_sessions WHERE order_id=o.order_id ORDER BY id DESC LIMIT 1) ps ON true "
            undelivered=[dict(r) for r in c.execute("SELECT o.order_id,o.rub_amount,o.currency,o.status,COALESCE(ps.provider,'?') provider,FLOOR(EXTRACT(EPOCH FROM(now()-r.created_at))/60)::int age_min"+base+"WHERE o.receipt_sent_at IS NULL AND o.status NOT IN('sent','cancelled') AND r.created_at<=now()-(%s*interval '1 minute') AND r.created_at>=now()-interval '24 hours' ORDER BY r.created_at",(int(undelivered_minutes),)).fetchall()]
            unresolved=[dict(r) for r in c.execute("SELECT o.order_id,o.rub_amount,o.currency,o.status,(o.receipt_sent_at IS NOT NULL) delivered,COALESCE(ps.provider,'?') provider,FLOOR(EXTRACT(EPOCH FROM(now()-r.created_at))/60)::int age_min"+base+"WHERE o.status NOT IN('paid','sent') AND NOT EXISTS(SELECT 1 FROM sent_notifications sn WHERE sn.order_id=o.order_id AND sn.event='receipt_rejected') AND r.created_at<=now()-(%s*interval '1 minute') AND r.created_at>=now()-(%s*interval '1 day') ORDER BY r.created_at",(int(unresolved_minutes),int(unresolved_days))).fetchall()]
        return {'issued':int(issued),'paid':int(paid),'early_expiry':int(early),'stuck_payouts':stuck,'undelivered_receipts':undelivered,'unresolved_receipts':unresolved}


def from_environment(*,sqlite_path):
    url=os.getenv('DATABASE_URL','').strip()
    if not url:return SQLiteOperationalReadStore(sqlite_path)
    if db_runtime.backend(url)!='postgresql' or os.getenv('OPERATIONAL_READ_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_operational_read_store_not_enabled')
    return PostgresOperationalReadStore(url)
