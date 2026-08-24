"""Order/referral ledger reconciliation and notification-outbox repository."""
from __future__ import annotations

import os
import json
import sqlite3
from typing import Any, Protocol

from core import db_runtime


def ensure_sqlite_schema(conn: sqlite3.Connection) -> None:
    conn.execute("SELECT order_id FROM payout_reconciliations WHERE 0")
    conn.execute("SELECT id FROM notification_outbox WHERE 0")


def _sqlite_dict(conn: sqlite3.Connection, sql: str, args=()) -> dict | None:
    old_factory = conn.row_factory
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(sql, args).fetchone()
        return dict(row) if row else None
    finally:
        conn.row_factory = old_factory


def reconcile_sqlite_order(conn: sqlite3.Connection, order_id: int, *,
                           btc_rate: float | None, commission_percent: float,
                           referral_percent: float) -> dict[str, Any]:
    oid = int(order_id)
    existing = _sqlite_dict(conn, "SELECT * FROM payout_reconciliations WHERE order_id=?", (oid,))
    if existing:
        return {"action": "already_reconciled", **existing}
    row = _sqlite_dict(conn, "SELECT p.id intent_id,p.txid,p.currency,p.network,"
                       "o.user_id,o.rub_amount,o.status FROM payout_intents p "
                       "JOIN orders o ON o.order_id=p.order_id WHERE p.order_id=? "
                       "AND p.state='succeeded' AND p.txid IS NOT NULL", (oid,))
    if not row:
        return {"action": "not_ready", "order_id": oid}
    if row["status"] != "paid":
        return {"action": "status_conflict", "order_id": oid, "status": row["status"]}
    referral = _sqlite_dict(conn, "SELECT referrer_id FROM referrals WHERE referred_id=?",
                            (row["user_id"],))
    bonus = 0.0
    if referral:
        if not btc_rate or float(btc_rate) <= 0:
            raise ValueError("btc_rate_required_for_referral")
        commission = float(row["rub_amount"]) * float(commission_percent) / 100
        bonus = round(commission * float(referral_percent) / 100 / float(btc_rate), 8)
    changed = conn.execute("UPDATE orders SET status='sent',paid_btc_tx=?,"
                           "updated_at=CURRENT_TIMESTAMP WHERE order_id=? AND status='paid'",
                           (row["txid"], oid))
    if changed.rowcount != 1:
        raise RuntimeError("order_transition_lost")
    if referral and bonus > 0:
        conn.execute("UPDATE referrals SET total_bonus_btc=total_bonus_btc+?,bonus_paid=0 "
                     "WHERE referrer_id=? AND referred_id=?",
                     (bonus, referral["referrer_id"], row["user_id"]))
    conn.execute("INSERT INTO user_vip_volume(user_id,total_rub,updated_at) "
                 "VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET "
                 "total_rub=total_rub+excluded.total_rub,updated_at=CURRENT_TIMESTAMP",
                 (row["user_id"], row["rub_amount"]))
    conn.execute("INSERT INTO payout_reconciliations"
                 "(order_id,intent_id,txid,referral_btc,vip_rub) VALUES(?,?,?,?,?)",
                 (oid, row["intent_id"], row["txid"], bonus, row["rub_amount"]))
    payload = json.dumps({"order_id": oid, "txid": row["txid"],
                          "currency": row["currency"], "network": row["network"]},
                         ensure_ascii=False, separators=(",", ":"))
    conn.execute("INSERT INTO notification_outbox(topic,aggregate_id,recipient_id,payload) "
                 "VALUES(?,?,?,?)", ("payout_sent", str(oid), row["user_id"], payload))
    return {"action": "reconciled", "order_id": oid, "txid": row["txid"],
            "user_id": row["user_id"], "referral_btc": bonus}


def reconcile_sqlite_referral(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = _sqlite_dict(conn, "SELECT * FROM referral_payout_intents "
                       "WHERE state='succeeded' ORDER BY id LIMIT 1")
    if not row:
        return None
    remaining = float(row["crypto_amount"])
    earned = conn.execute("SELECT rowid,total_bonus_btc FROM referrals WHERE referrer_id=? "
                          "AND total_bonus_btc>0 ORDER BY rowid", (row["user_id"],)).fetchall()
    if sum(float(item[1]) for item in earned) + 1e-12 < remaining:
        raise RuntimeError("referral_reserved_balance_missing")
    for rowid, amount in earned:
        take = min(float(amount), remaining)
        conn.execute("UPDATE referrals SET total_bonus_btc=total_bonus_btc-? WHERE rowid=?",
                     (take, rowid))
        remaining -= take
        if remaining <= 1e-12:
            break
    changed = conn.execute("UPDATE referral_payout_intents SET state='reconciled',"
                           "updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='succeeded'",
                           (row["id"],))
    if changed.rowcount != 1:
        raise RuntimeError("referral_reconciliation_lost")
    payload = json.dumps({"intent_id": row["id"], "txid": row["txid"],
                          "currency": "BTC", "network": None}, separators=(",", ":"))
    conn.execute("INSERT INTO notification_outbox(topic,aggregate_id,recipient_id,payload) "
                 "VALUES('referral_payout_sent',?,?,?)",
                 (str(row["id"]), row["user_id"], payload))
    return row


def claim_sqlite_notification(conn: sqlite3.Connection) -> dict[str, Any] | None:
    row = conn.execute("SELECT id FROM notification_outbox WHERE state='pending' "
                       "ORDER BY id LIMIT 1").fetchone()
    if not row:
        return None
    ident = int(row[0])
    changed = conn.execute("UPDATE notification_outbox SET state='sending',"
                           "attempts=attempts+1,claimed_at=CURRENT_TIMESTAMP,"
                           "updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='pending'", (ident,))
    if changed.rowcount != 1:
        return None
    return _sqlite_dict(conn, "SELECT * FROM notification_outbox WHERE id=?", (ident,))


def mark_sqlite_notification_sent(conn: sqlite3.Connection, ident: int) -> bool:
    return conn.execute("UPDATE notification_outbox SET state='sent',sent_at=CURRENT_TIMESTAMP,"
                        "updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='sending'",
                        (int(ident),)).rowcount == 1


def retry_sqlite_notification(conn: sqlite3.Connection, ident: int) -> bool:
    return conn.execute("UPDATE notification_outbox SET state='pending',claimed_at=NULL,"
                        "updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='sending'",
                        (int(ident),)).rowcount == 1


class ReconciliationStore(Protocol):
    def pending_orders(self, limit: int = 20) -> list[dict[str, Any]]: ...
    def reconcile_order(self, order_id: int, *, btc_rate: float | None,
                        commission_percent: float, referral_percent: float) -> dict: ...
    def reconcile_referral(self) -> dict | None: ...
    def claim_notification(self) -> dict | None: ...
    def mark_notification_sent(self, ident: int) -> bool: ...
    def retry_notification(self, ident: int) -> bool: ...


class SQLiteReconciliationStore:
    def __init__(self, path: str, *, timeout: float = 10):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def pending_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT p.order_id,o.rub_amount FROM payout_intents p "
                "JOIN orders o ON o.order_id=p.order_id "
                "WHERE p.state='succeeded' AND o.status='paid' "
                "ORDER BY p.finished_at,p.id LIMIT ?", (limit,)).fetchall()
        return [{"order_id": int(row[0]), "rub_amount": float(row[1])} for row in rows]

    def reconcile_order(self, order_id: int, *, btc_rate: float | None,
                        commission_percent: float, referral_percent: float) -> dict:
        with self._connect() as conn:
            ensure_sqlite_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            result = reconcile_sqlite_order(
                conn, order_id, btc_rate=btc_rate,
                commission_percent=commission_percent,
                referral_percent=referral_percent)
            conn.commit()
            return result

    def reconcile_referral(self) -> dict | None:
        with self._connect() as conn:
            ensure_sqlite_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            result = reconcile_sqlite_referral(conn)
            conn.commit()
            return result

    def claim_notification(self) -> dict | None:
        with self._connect() as conn:
            ensure_sqlite_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            item = claim_sqlite_notification(conn)
            conn.commit()
            return item

    def mark_notification_sent(self, ident: int) -> bool:
        with self._connect() as conn:
            ok = mark_sqlite_notification_sent(conn, ident)
            conn.commit()
            return ok

    def retry_notification(self, ident: int) -> bool:
        with self._connect() as conn:
            ok = retry_sqlite_notification(conn, ident)
            conn.commit()
            return ok


class PostgresReconciliationStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def pending_orders(self, limit: int = 20) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT p.order_id,o.rub_amount FROM payout_intents p "
                        "JOIN orders o ON o.order_id=p.order_id "
                        "WHERE p.state='succeeded' AND o.status='paid' "
                        "ORDER BY p.finished_at,p.id LIMIT %s", (limit,))
            return [{"order_id":int(row["order_id"]),"rub_amount":float(row["rub_amount"])}
                    for row in cur.fetchall()]

    def reconcile_order(self, order_id: int, *, btc_rate: float | None,
                        commission_percent: float, referral_percent: float) -> dict:
        oid = int(order_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM payout_reconciliations WHERE order_id=%s", (oid,))
            existing = cur.fetchone()
            if existing:
                return {"action": "already_reconciled", **dict(existing)}
            cur.execute("SELECT p.id intent_id,p.txid,p.currency,p.network,"
                        "o.user_id,o.rub_amount,o.status FROM payout_intents p "
                        "JOIN orders o ON o.order_id=p.order_id WHERE p.order_id=%s "
                        "AND p.state='succeeded' AND p.txid IS NOT NULL FOR UPDATE OF p,o", (oid,))
            row = cur.fetchone()
            if not row:
                return {"action": "not_ready", "order_id": oid}
            if row["status"] != "paid":
                return {"action": "status_conflict", "order_id": oid, "status": row["status"]}
            cur.execute("SELECT referrer_id FROM referrals WHERE referred_id=%s FOR UPDATE",
                        (row["user_id"],))
            referral = cur.fetchone(); bonus = 0.0
            if referral:
                if not btc_rate or float(btc_rate) <= 0:
                    raise ValueError("btc_rate_required_for_referral")
                commission = float(row["rub_amount"]) * float(commission_percent) / 100
                bonus = round(commission * float(referral_percent) / 100 / float(btc_rate), 8)
            cur.execute("UPDATE orders SET status='sent',paid_btc_tx=%s,updated_at=now() "
                        "WHERE order_id=%s AND status='paid'", (row["txid"], oid))
            if cur.rowcount != 1:
                raise RuntimeError("order_transition_lost")
            if referral and bonus > 0:
                cur.execute("UPDATE referrals SET total_bonus_btc=total_bonus_btc+%s,bonus_paid=false "
                            "WHERE referrer_id=%s AND referred_id=%s",
                            (bonus, referral["referrer_id"], row["user_id"]))
            cur.execute("INSERT INTO user_vip_volume(user_id,total_rub,updated_at) "
                        "VALUES(%s,%s,now()) ON CONFLICT(user_id) DO UPDATE SET "
                        "total_rub=user_vip_volume.total_rub+excluded.total_rub,updated_at=now()",
                        (row["user_id"], row["rub_amount"]))
            cur.execute("INSERT INTO payout_reconciliations"
                        "(order_id,intent_id,txid,referral_btc,vip_rub) VALUES(%s,%s,%s,%s,%s)",
                        (oid,row["intent_id"],row["txid"],bonus,row["rub_amount"]))
            payload = json.dumps({"order_id":oid,"txid":row["txid"],
                                  "currency":row["currency"],"network":row["network"]})
            cur.execute("INSERT INTO notification_outbox(topic,aggregate_id,recipient_id,payload) "
                        "VALUES('payout_sent',%s,%s,%s::jsonb)",
                        (str(oid),row["user_id"],payload))
            conn.commit()
            return {"action":"reconciled","order_id":oid,"txid":row["txid"],
                    "user_id":row["user_id"],"referral_btc":bonus}

    def reconcile_referral(self) -> dict | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM referral_payout_intents WHERE state='succeeded' "
                        "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1")
            intent = cur.fetchone()
            if not intent:
                return None
            cur.execute("SELECT referred_id,total_bonus_btc FROM referrals "
                        "WHERE referrer_id=%s AND total_bonus_btc>0 "
                        "ORDER BY referred_id FOR UPDATE", (intent["user_id"],))
            earned = cur.fetchall(); remaining = float(intent["crypto_amount"])
            if sum(float(row["total_bonus_btc"]) for row in earned)+1e-12 < remaining:
                raise RuntimeError("referral_reserved_balance_missing")
            for row in earned:
                take=min(float(row["total_bonus_btc"]),remaining)
                cur.execute("UPDATE referrals SET total_bonus_btc=total_bonus_btc-%s "
                            "WHERE referrer_id=%s AND referred_id=%s",
                            (take,intent["user_id"],row["referred_id"]))
                remaining-=take
                if remaining<=1e-12: break
            cur.execute("UPDATE referral_payout_intents SET state='reconciled',updated_at=now() "
                        "WHERE id=%s AND state='succeeded'", (intent["id"],))
            if cur.rowcount != 1: raise RuntimeError("referral_reconciliation_lost")
            payload=json.dumps({"intent_id":intent["id"],"txid":intent["txid"],
                                "currency":"BTC","network":None})
            cur.execute("INSERT INTO notification_outbox(topic,aggregate_id,recipient_id,payload) "
                        "VALUES('referral_payout_sent',%s,%s,%s::jsonb)",
                        (str(intent["id"]),intent["user_id"],payload))
            conn.commit(); return dict(intent)

    def claim_notification(self) -> dict | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("WITH candidate AS (SELECT id FROM notification_outbox "
                        "WHERE state='pending' ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) "
                        "UPDATE notification_outbox n SET state='sending',attempts=n.attempts+1,"
                        "claimed_at=now(),updated_at=now() FROM candidate c WHERE n.id=c.id "
                        "RETURNING n.*")
            row=cur.fetchone(); conn.commit()
            if not row: return None
            item=dict(row)
            if isinstance(item.get("payload"), dict):
                item["payload"]=json.dumps(item["payload"], separators=(",",":"))
            return item

    def _outbox_state(self, ident: int, state: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            if state == "sent":
                cur.execute("UPDATE notification_outbox SET state='sent',sent_at=now(),updated_at=now() "
                            "WHERE id=%s AND state='sending'", (int(ident),))
            else:
                cur.execute("UPDATE notification_outbox SET state='pending',claimed_at=NULL,updated_at=now() "
                            "WHERE id=%s AND state='sending'", (int(ident),))
            ok=cur.rowcount==1; conn.commit(); return ok

    def mark_notification_sent(self, ident: int) -> bool:
        return self._outbox_state(ident,"sent")

    def retry_notification(self, ident: int) -> bool:
        return self._outbox_state(ident,"pending")


def from_environment(*, sqlite_path: str) -> ReconciliationStore:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteReconciliationStore(sqlite_path)
    gates = ("PAYOUT_POSTGRES_ENABLED", "RECONCILIATION_POSTGRES_ENABLED")
    if db_runtime.backend(url) != "postgresql" or any(
        os.getenv(key,"").strip().lower() not in {"1","true","yes"} for key in gates):
        raise RuntimeError("postgres_reconciliation_store_not_enabled")
    return PostgresReconciliationStore(url)
