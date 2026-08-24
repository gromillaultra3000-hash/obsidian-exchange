"""Persistence boundary for payout-guard shadow decisions."""
from __future__ import annotations

import os
import sqlite3
from core import db_runtime


class SQLiteShadowPayoutStore:
    def __init__(self, path, *, timeout=5): self.path, self.timeout = path, timeout
    def _c(self):
        connection = db_runtime.sqlite_connect(self.path, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        return connection
    def pending_orders(self, limit):
        with self._c() as c:
            return [dict(r) for r in c.execute(
                "SELECT o.order_id,o.rub_amount,o.currency,o.crypto_address FROM orders o "
                "WHERE o.status IN ('paid','sent') AND o.created_at>=datetime('now','-14 days') "
                "AND NOT EXISTS(SELECT 1 FROM payout_shadow s WHERE s.order_id=o.order_id) "
                "ORDER BY o.order_id DESC LIMIT ?", (limit,)).fetchall()]
    def record(self, order_id, verdict, detail, provider, action, would_pay, rub_amount, currency):
        with self._c() as c:
            c.execute("INSERT INTO payout_shadow(order_id,verdict,detail,provider,circuit_action,would_auto_pay,rub_amount,currency) VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(order_id) DO UPDATE SET verdict=excluded.verdict,detail=excluded.detail,provider=excluded.provider,circuit_action=excluded.circuit_action,would_auto_pay=excluded.would_auto_pay,rub_amount=excluded.rub_amount,currency=excluded.currency",
                      (order_id, verdict, detail, provider, action, would_pay, rub_amount, currency)); c.commit()
    def sync_outcomes(self):
        with self._c() as c:
            q = c.execute("UPDATE payout_shadow SET outcome=(SELECT CASE WHEN o.status='sent' AND o.paid_btc_tx LIKE 'manual%' THEN 'отправлено вручную' WHEN o.status='sent' THEN 'отправлено (авто/txid)' WHEN o.status='paid' THEN 'ещё не отправлено' ELSE o.status END FROM orders o WHERE o.order_id=payout_shadow.order_id),outcome_at=datetime('now') WHERE outcome IS NULL OR outcome='ещё не отправлено'"); c.commit(); return q.rowcount
    def recent(self, days):
        with self._c() as c: return [dict(r) for r in c.execute("SELECT * FROM payout_shadow WHERE decided_at>=datetime('now',?)", (f"-{days} days",)).fetchall()]


class PostgresShadowPayoutStore(SQLiteShadowPayoutStore):
    def __init__(self, dsn): self.dsn = dsn
    def _c(self):
        import psycopg
        return psycopg.connect(self.dsn, row_factory=psycopg.rows.dict_row)
    def pending_orders(self, limit):
        with self._c() as c: return c.execute("SELECT o.order_id,o.rub_amount,o.currency,o.crypto_address FROM orders o WHERE o.status IN ('paid','sent') AND o.created_at>=now()-interval '14 days' AND NOT EXISTS(SELECT 1 FROM payout_shadow s WHERE s.order_id=o.order_id) ORDER BY o.order_id DESC LIMIT %s", (limit,)).fetchall()
    def record(self, order_id, verdict, detail, provider, action, would_pay, rub_amount, currency):
        with self._c() as c: c.execute("INSERT INTO payout_shadow(order_id,verdict,detail,provider,circuit_action,would_auto_pay,rub_amount,currency) VALUES(%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(order_id) DO UPDATE SET verdict=excluded.verdict,detail=excluded.detail,provider=excluded.provider,circuit_action=excluded.circuit_action,would_auto_pay=excluded.would_auto_pay,rub_amount=excluded.rub_amount,currency=excluded.currency", (order_id,verdict,detail,provider,action,bool(would_pay),rub_amount,currency))
    def sync_outcomes(self):
        with self._c() as c:
            q=c.execute("UPDATE payout_shadow s SET outcome=CASE WHEN o.status='sent' AND o.paid_btc_tx LIKE 'manual%%' THEN 'отправлено вручную' WHEN o.status='sent' THEN 'отправлено (авто/txid)' WHEN o.status='paid' THEN 'ещё не отправлено' ELSE o.status END,outcome_at=now() FROM orders o WHERE o.order_id=s.order_id AND (s.outcome IS NULL OR s.outcome='ещё не отправлено')"); return q.rowcount
    def recent(self, days):
        with self._c() as c: return c.execute("SELECT * FROM payout_shadow WHERE decided_at>=now()-(%s * interval '1 day')", (days,)).fetchall()


def from_environment(*, sqlite_path):
    url=os.getenv('DATABASE_URL','').strip()
    if not url:return SQLiteShadowPayoutStore(sqlite_path)
    if db_runtime.backend(url)!='postgresql' or os.getenv('SHADOW_PAYOUT_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_shadow_payout_store_not_enabled')
    return PostgresShadowPayoutStore(url)
