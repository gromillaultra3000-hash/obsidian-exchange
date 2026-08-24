"""Atomic payment confirmation, evidence ledger, and customer outbox."""
from __future__ import annotations

import json
import os
from typing import Any, Protocol

from core import db_runtime


class PaymentTransitionStore(Protocol):
    def mark_paid(self, order_id: int, *, provider: str, evidence: str,
                  session_token: str | None = None) -> dict[str, Any]: ...
    def claim_notification(self) -> dict[str, Any] | None: ...
    def mark_notification_sent(self, ident: int) -> bool: ...
    def retry_notification(self, ident: int) -> bool: ...


class SQLitePaymentTransitionStore:
    def __init__(self, path: str, *, timeout: float = 10):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def mark_paid(self, order_id: int, *, provider: str, evidence: str,
                  session_token: str | None = None):
        oid = int(order_id)
        provider = str(provider or "").strip()
        if not provider or len(provider) > 80:
            raise ValueError("invalid_payment_provider")
        if session_token is not None and len(str(session_token)) > 256:
            raise ValueError("invalid_session_token")
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status,user_id FROM orders WHERE order_id=?", (oid,)).fetchone()
            if not row:
                conn.rollback()
                return {"action": "missing", "order_id": oid}
            current, user_id = row
            if current == "paid":
                conn.rollback()
                return {"action": "already_paid", "order_id": oid, "user_id": user_id}
            if current != "pending":
                conn.rollback()
                return {"action": "status_conflict", "order_id": oid, "status": current}
            changed = conn.execute(
                "UPDATE orders SET status='paid',updated_at=CURRENT_TIMESTAMP "
                "WHERE order_id=? AND status='pending'", (oid,)).rowcount
            if changed != 1:
                raise RuntimeError("payment_transition_lost")
            if session_token:
                conn.execute("UPDATE payment_sessions SET status='paid',updated_at=CURRENT_TIMESTAMP "
                             "WHERE order_id=? AND session_token=? AND status NOT IN('failed','expired')",
                             (oid, session_token))
            else:
                conn.execute("UPDATE payment_sessions SET status='paid',updated_at=CURRENT_TIMESTAMP "
                             "WHERE id=(SELECT id FROM payment_sessions WHERE order_id=? "
                             "AND provider LIKE ? AND status NOT IN('failed','expired') "
                             "ORDER BY id DESC LIMIT 1)", (oid, provider + "%"))
            conn.execute("UPDATE gift_vouchers SET status='paid' WHERE order_id=? AND status='pending'",(oid,))
            conn.execute("INSERT INTO payment_transition_audit"
                         "(order_id,provider,action,from_status,to_status,evidence) "
                         "VALUES(?,?, 'confirm', 'pending', 'paid', ?)",
                         (oid, provider, evidence[:160]))
            if user_id and int(user_id) > 0:
                payload = json.dumps({"order_id": oid}, separators=(",", ":"))
                conn.execute("INSERT OR IGNORE INTO payment_notification_outbox"
                             "(order_id,recipient_id,payload) VALUES(?,?,?)",
                             (oid, int(user_id), payload))
            conn.commit()
            return {"action": "transitioned", "order_id": oid, "user_id": user_id}

    def claim_notification(self):
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT id FROM payment_notification_outbox "
                               "WHERE state='pending' ORDER BY id LIMIT 1").fetchone()
            if not row:
                conn.commit()
                return None
            ident = int(row[0])
            conn.execute("UPDATE payment_notification_outbox SET state='sending',"
                         "attempts=attempts+1,claimed_at=CURRENT_TIMESTAMP,"
                         "updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='pending'", (ident,))
            item = conn.execute("SELECT id,order_id,recipient_id,payload,attempts "
                                "FROM payment_notification_outbox WHERE id=?", (ident,)).fetchone()
            conn.commit()
            return dict(zip(("id", "order_id", "recipient_id", "payload", "attempts"), item))

    def _state(self, ident: int, sent: bool) -> bool:
        with self._connect() as conn:
            if sent:
                cur = conn.execute("UPDATE payment_notification_outbox SET state='sent',"
                                   "sent_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
                                   "WHERE id=? AND state='sending'", (int(ident),))
            else:
                cur = conn.execute("UPDATE payment_notification_outbox SET state='pending',"
                                   "claimed_at=NULL,updated_at=CURRENT_TIMESTAMP "
                                   "WHERE id=? AND state='sending'", (int(ident),))
            conn.commit()
            return cur.rowcount == 1

    def mark_notification_sent(self, ident: int) -> bool:
        return self._state(ident, True)

    def retry_notification(self, ident: int) -> bool:
        return self._state(ident, False)


class PostgresPaymentTransitionStore:
    def __init__(self, dsn: str): self.dsn = dsn
    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def mark_paid(self, order_id: int, *, provider: str, evidence: str,
                  session_token: str | None = None):
        oid = int(order_id)
        provider = str(provider or "").strip()
        if not provider or len(provider) > 80:
            raise ValueError("invalid_payment_provider")
        if session_token is not None and len(str(session_token)) > 256:
            raise ValueError("invalid_session_token")
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT status,user_id FROM orders WHERE order_id=%s FOR UPDATE", (oid,))
            row = cur.fetchone()
            if not row: return {"action":"missing","order_id":oid}
            if row["status"] == "paid":
                return {"action":"already_paid","order_id":oid,"user_id":row["user_id"]}
            if row["status"] != "pending":
                return {"action":"status_conflict","order_id":oid,"status":row["status"]}
            cur.execute("UPDATE orders SET status='paid',updated_at=now() WHERE order_id=%s", (oid,))
            if session_token:
                cur.execute("UPDATE payment_sessions SET status='paid',updated_at=now() WHERE "
                            "order_id=%s AND session_token=%s AND status NOT IN('failed','expired')",
                            (oid, session_token))
            else:
                cur.execute("UPDATE payment_sessions SET status='paid',updated_at=now() WHERE id=("
                            "SELECT id FROM payment_sessions WHERE order_id=%s AND provider LIKE %s "
                            "AND status NOT IN('failed','expired') ORDER BY id DESC LIMIT 1)",
                            (oid, provider + "%"))
            cur.execute("UPDATE gift_vouchers SET status='paid' WHERE order_id=%s AND status='pending'",(oid,))
            cur.execute("INSERT INTO payment_transition_audit"
                        "(order_id,provider,action,from_status,to_status,evidence) "
                        "VALUES(%s,%s,'confirm','pending','paid',%s)",
                        (oid, provider, evidence[:160]))
            if row["user_id"] and int(row["user_id"]) > 0:
                cur.execute("INSERT INTO payment_notification_outbox(order_id,recipient_id,payload) "
                            "VALUES(%s,%s,%s::jsonb) ON CONFLICT(order_id) DO NOTHING",
                            (oid, row["user_id"], json.dumps({"order_id":oid})))
            return {"action":"transitioned","order_id":oid,"user_id":row["user_id"]}

    def claim_notification(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("WITH c AS (SELECT id FROM payment_notification_outbox WHERE state='pending' "
                        "ORDER BY id FOR UPDATE SKIP LOCKED LIMIT 1) UPDATE payment_notification_outbox o "
                        "SET state='sending',attempts=o.attempts+1,claimed_at=now(),updated_at=now() "
                        "FROM c WHERE o.id=c.id RETURNING o.id,o.order_id,o.recipient_id,o.payload,"
                        "o.attempts")
            row=cur.fetchone(); return dict(row) if row else None

    def _state(self, ident: int, sent: bool) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            if sent:
                cur.execute("UPDATE payment_notification_outbox SET state='sent',sent_at=now(),"
                            "updated_at=now() WHERE id=%s AND state='sending'", (int(ident),))
            else:
                cur.execute("UPDATE payment_notification_outbox SET state='pending',claimed_at=NULL,"
                            "updated_at=now() WHERE id=%s AND state='sending'", (int(ident),))
            return cur.rowcount == 1
    def mark_notification_sent(self, ident: int) -> bool: return self._state(ident, True)
    def retry_notification(self, ident: int) -> bool: return self._state(ident, False)


def from_environment(*, sqlite_path: str) -> PaymentTransitionStore:
    url=os.getenv("DATABASE_URL","").strip()
    if not url: return SQLitePaymentTransitionStore(sqlite_path)
    if (db_runtime.backend(url)!="postgresql" or
        os.getenv("PAYMENT_POSTGRES_ENABLED","").strip().lower() not in {"1","true","yes"}):
        raise RuntimeError("postgres_payment_transition_store_not_enabled")
    return PostgresPaymentTransitionStore(url)
