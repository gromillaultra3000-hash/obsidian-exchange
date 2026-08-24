"""Payment-session creation, lookup and forward state changes."""
from __future__ import annotations

import os
from typing import Any

from core import db_runtime
from services.state_machine import PaymentStateMachine


def _order_authority(user_id, session_token):
    uid = int(user_id) if user_id is not None else None
    token = str(session_token or "").strip()
    if uid is not None and uid <= 0:
        raise ValueError("invalid_order_authority_user")
    if len(token) > 256:
        raise ValueError("invalid_order_authority_token")
    if uid is None and not token:
        raise ValueError("missing_order_authority")
    return uid, token or None


class SQLitePaymentSessionStore:
    def __init__(self, path: str, *, timeout: float = 5):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def create_failed(self, *, token: str, order_id: int, amount: float,
                      provider: str = "fallback") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO payment_sessions(session_token,order_id,amount,provider,status) "
                "VALUES(?,?,?,?,'failed')", (token, order_id, amount, provider))
            conn.commit()

    def create_invoice(self, *, token: str, order_id: int, amount: float, provider: str,
                       expires_at, client_ip: str | None, user_agent: str | None,
                       telegram_id: int | None, invoice_id: str | None,
                       qr_payload: str | None, provider_payload: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                "INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,"
                "expires_at,client_ip,user_agent,telegram_id,provider_invoice_id,qr_payload,"
                "provider_payload) VALUES(?,?,?,?,'invoice_created',?,?,?,?,?,?,?)",
                (token, order_id, amount, provider, expires_at, client_ip, user_agent,
                 telegram_id, invoice_id, qr_payload, provider_payload))
            conn.commit()

    def get(self, token: str) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute("SELECT * FROM payment_sessions WHERE session_token=?", (token,))
            row, columns = cur.fetchone(), [item[0] for item in cur.description]
        return dict(zip(columns, row)) if row else None

    def get_by_token(self, token: str) -> dict[str, Any] | None:
        value = str(token or "").strip()
        if not value or len(value) > 256:
            return None
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT amount,order_id,status,provider_payload,qr_payload,expires_at "
                "FROM payment_sessions WHERE session_token=? LIMIT 1", (value,))
            row, columns = cur.fetchone(), [item[0] for item in cur.description]
        return dict(zip(columns, row)) if row else None

    def latest_for_order(self, order_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT session_token,status FROM payment_sessions WHERE order_id=? "
                "ORDER BY id DESC LIMIT 1",
                (int(order_id),))
            row, columns = cur.fetchone(), [item[0] for item in cur.description]
        return dict(zip(columns, row)) if row else None

    def latest_for_authorized_order(self, order_id: int, *, user_id=None,
                                    session_token=None) -> dict[str, Any] | None:
        uid, token = _order_authority(user_id, session_token)
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ps.session_token,ps.status FROM payment_sessions ps JOIN orders o "
                "ON o.order_id=ps.order_id WHERE ps.order_id=? AND (o.user_id=? OR "
                "EXISTS(SELECT 1 FROM payment_sessions proof WHERE proof.order_id=o.order_id "
                "AND proof.session_token=?)) ORDER BY ps.id DESC LIMIT 1",
                (int(order_id), uid, token))
            row, columns = cur.fetchone(), [item[0] for item in cur.description]
        return dict(zip(columns, row)) if row else None

    def recent_for_order(self, order_id: int, *, limit: int = 3) -> list[dict[str, Any]]:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT provider,provider_invoice_id,amount,status,created_at "
                "FROM payment_sessions WHERE order_id=? ORDER BY id DESC LIMIT ?",
                (int(order_id), min(100, max(1, int(limit)))))
            rows, columns = cur.fetchall(), [item[0] for item in cur.description]
        return [dict(zip(columns, row)) for row in rows]

    def latest_active_for_order(self, order_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT session_token FROM payment_sessions WHERE order_id=? "
                "AND session_token IS NOT NULL AND status NOT IN('failed','expired') "
                "ORDER BY created_at DESC,id DESC LIMIT 1", (int(order_id),))
            row, columns = cur.fetchone(), [item[0] for item in cur.description]
        return dict(zip(columns, row)) if row else None

    def latest_active_for_authorized_order(self, order_id: int, *, user_id=None,
                                           session_token=None) -> dict[str, Any] | None:
        uid, token = _order_authority(user_id, session_token)
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ps.session_token FROM payment_sessions ps JOIN orders o "
                "ON o.order_id=ps.order_id WHERE ps.order_id=? AND ps.session_token IS NOT NULL "
                "AND ps.status NOT IN('failed','expired') AND (o.user_id=? OR "
                "EXISTS(SELECT 1 FROM payment_sessions proof WHERE proof.order_id=o.order_id "
                "AND proof.session_token=?)) ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1",
                (int(order_id), uid, token))
            row, columns = cur.fetchone(), [item[0] for item in cur.description]
        return dict(zip(columns, row)) if row else None

    def token_matches_order(self, order_id: int, token: str) -> bool:
        if not str(token or ""):
            return False
        with self._connect() as conn:
            row = conn.execute(
                "SELECT 1 FROM payment_sessions WHERE order_id=? AND session_token=? LIMIT 1",
                (int(order_id), str(token))).fetchone()
        return row is not None

    def latest_provider_invoice(self, order_id: int, provider: str, *,
                                prefix: bool = False) -> dict[str, Any] | None:
        comparison = "LIKE ?" if prefix else "=?"
        value = f"{provider}%" if prefix else provider
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT provider_invoice_id,provider FROM payment_sessions "
                f"WHERE order_id=? AND provider{comparison} "
                "AND provider_invoice_id IS NOT NULL ORDER BY created_at DESC,id DESC LIMIT 1",
                (int(order_id), value))
            row = cur.fetchone()
        return ({"provider_invoice_id": row[0], "provider": row[1]} if row else None)

    def latest_provider_invoice_for_authorized_order(
            self, order_id: int, provider: str, *, user_id=None,
            session_token=None, prefix: bool = False) -> dict[str, Any] | None:
        uid, token = _order_authority(user_id, session_token)
        comparison = "LIKE ?" if prefix else "=?"
        value = f"{provider}%" if prefix else provider
        with self._connect() as conn:
            cur = conn.execute(
                "SELECT ps.provider_invoice_id,ps.provider FROM payment_sessions ps "
                "JOIN orders o ON o.order_id=ps.order_id "
                f"WHERE ps.order_id=? AND ps.provider{comparison} "
                "AND ps.provider_invoice_id IS NOT NULL AND (o.user_id=? OR "
                "EXISTS(SELECT 1 FROM payment_sessions proof WHERE proof.order_id=o.order_id "
                "AND proof.session_token=?)) ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1",
                (int(order_id), value, uid, token))
            row = cur.fetchone()
        return ({"provider_invoice_id": row[0], "provider": row[1]} if row else None)

    def pending_vertu(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT ps.session_token,ps.provider_invoice_id,ps.order_id "
                "FROM payment_sessions ps JOIN orders o ON o.order_id=ps.order_id "
                "WHERE ps.provider='vertu' AND ps.status='invoice_created' "
                "AND ps.provider_invoice_id IS NOT NULL AND o.status='pending' "
                "AND datetime(ps.created_at)>datetime('now','-2 hours') "
                "ORDER BY ps.id LIMIT 100").fetchall()
        keys = ("session_token", "provider_invoice_id", "order_id")
        return [dict(zip(keys, row)) for row in rows]

    def transition(self, token: str, new_status: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT status FROM payment_sessions WHERE session_token=?",
                               (token,)).fetchone()
            if not row:
                return False
            PaymentStateMachine.transition(row[0], new_status)
            changed = conn.execute(
                "UPDATE payment_sessions SET status=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE session_token=? AND status=?", (new_status, token, row[0])).rowcount
            conn.commit()
            return changed == 1

    def active(self) -> list[dict[str, Any]]:
        with self._connect() as conn:
            rows = conn.execute(
                "SELECT session_token,provider_invoice_id,created_at,expires_at "
                "FROM payment_sessions WHERE status IN('invoice_created','awaiting_payment')"
            ).fetchall()
        keys = ("session_token", "provider_invoice_id", "created_at", "expires_at")
        return [dict(zip(keys, row)) for row in rows]

    def expire(self, token: str) -> bool:
        with self._connect() as conn:
            changed = conn.execute(
                "UPDATE payment_sessions SET status='expired',updated_at=CURRENT_TIMESTAMP "
                "WHERE session_token=? AND status IN('invoice_created','awaiting_payment')",
                (token,)).rowcount
            conn.commit()
            return changed == 1


class PostgresPaymentSessionStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def create_failed(self, *, token: str, order_id: int, amount: float,
                      provider: str = "fallback") -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO payment_sessions(session_token,order_id,amount,provider,status) "
                "VALUES(%s,%s,%s,%s,'failed')", (token, order_id, amount, provider))

    def create_invoice(self, *, token: str, order_id: int, amount: float, provider: str,
                       expires_at, client_ip: str | None, user_agent: str | None,
                       telegram_id: int | None, invoice_id: str | None,
                       qr_payload: str | None, provider_payload: str) -> None:
        with self._connect() as conn:
            conn.execute(
                "INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,"
                "expires_at,client_ip,user_agent,telegram_id,provider_invoice_id,qr_payload,"
                "provider_payload) VALUES(%s,%s,%s,%s,'invoice_created',%s,%s,%s,%s,%s,%s,%s)",
                (token, order_id, amount, provider, expires_at, client_ip, user_agent,
                 telegram_id, invoice_id, qr_payload, provider_payload))

    def get(self, token: str):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM payment_sessions WHERE session_token=%s", (token,))
            row = cur.fetchone()
            return dict(row) if row else None

    def get_by_token(self, token: str):
        value = str(token or "").strip()
        if not value or len(value) > 256:
            return None
        with self._connect() as conn, conn.cursor() as cur:
            if os.getenv("RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED", "").lower() in {"1", "true", "yes"}:
                cur.execute("SELECT * FROM public.relay_payment_session_get_by_token(%s::text)",
                            (value,))
            else:
                cur.execute("SELECT amount,order_id,status,provider_payload,qr_payload,expires_at "
                            "FROM payment_sessions WHERE session_token=%s LIMIT 1", (value,))
            row = cur.fetchone()
            return dict(row) if row else None

    def latest_for_order(self, order_id: int):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT session_token,status FROM payment_sessions WHERE order_id=%s "
                        "ORDER BY id DESC LIMIT 1", (int(order_id),))
            row = cur.fetchone()
            return dict(row) if row else None

    def latest_for_authorized_order(self, order_id: int, *, user_id=None,
                                    session_token=None):
        uid, token = _order_authority(user_id, session_token)
        with self._connect() as conn, conn.cursor() as cur:
            if os.getenv("RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED", "").lower() in {"1", "true", "yes"}:
                cur.execute("SELECT * FROM public.relay_payment_session_latest_for_authorized_order(%s::bigint,%s::bigint,%s::text)",
                            (int(order_id), uid, token))
            else:
                cur.execute("SELECT ps.session_token,ps.status FROM payment_sessions ps JOIN orders o "
                            "ON o.order_id=ps.order_id WHERE ps.order_id=%s AND (o.user_id=%s OR "
                            "EXISTS(SELECT 1 FROM payment_sessions proof WHERE proof.order_id=o.order_id "
                            "AND proof.session_token=%s)) ORDER BY ps.id DESC LIMIT 1",
                            (int(order_id), uid, token))
            row = cur.fetchone()
            return dict(row) if row else None

    def recent_for_order(self, order_id: int, *, limit: int = 3):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT provider,provider_invoice_id,amount,status,created_at "
                        "FROM payment_sessions WHERE order_id=%s ORDER BY id DESC LIMIT %s",
                        (int(order_id), min(100, max(1, int(limit)))))
            return [dict(row) for row in cur.fetchall()]

    def latest_active_for_order(self, order_id: int):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT session_token FROM payment_sessions WHERE order_id=%s "
                        "AND session_token IS NOT NULL AND status NOT IN('failed','expired') "
                        "ORDER BY created_at DESC,id DESC LIMIT 1", (int(order_id),))
            row = cur.fetchone()
            return dict(row) if row else None

    def latest_active_for_authorized_order(self, order_id: int, *, user_id=None,
                                           session_token=None):
        uid, token = _order_authority(user_id, session_token)
        with self._connect() as conn, conn.cursor() as cur:
            if os.getenv("RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED", "").lower() in {"1", "true", "yes"}:
                cur.execute("SELECT * FROM public.relay_payment_session_latest_active_for_authorized_order(%s::bigint,%s::bigint,%s::text)",
                            (int(order_id), uid, token))
            else:
                cur.execute("SELECT ps.session_token FROM payment_sessions ps JOIN orders o "
                            "ON o.order_id=ps.order_id WHERE ps.order_id=%s "
                            "AND ps.session_token IS NOT NULL AND ps.status NOT IN('failed','expired') "
                            "AND (o.user_id=%s OR EXISTS(SELECT 1 FROM payment_sessions proof "
                            "WHERE proof.order_id=o.order_id AND proof.session_token=%s)) "
                            "ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1",
                            (int(order_id), uid, token))
            row = cur.fetchone()
            return dict(row) if row else None

    def token_matches_order(self, order_id: int, token: str) -> bool:
        if not str(token or ""):
            return False
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM payment_sessions WHERE order_id=%s "
                        "AND session_token=%s LIMIT 1", (int(order_id), str(token)))
            return cur.fetchone() is not None

    def latest_provider_invoice(self, order_id: int, provider: str, *,
                                prefix: bool = False):
        operator = "LIKE" if prefix else "="
        value = f"{provider}%" if prefix else provider
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT provider_invoice_id,provider FROM payment_sessions "
                        f"WHERE order_id=%s AND provider {operator} %s "
                        "AND provider_invoice_id IS NOT NULL "
                        "ORDER BY created_at DESC,id DESC LIMIT 1", (int(order_id), value))
            row = cur.fetchone()
            return dict(row) if row else None

    def latest_provider_invoice_for_authorized_order(
            self, order_id: int, provider: str, *, user_id=None,
            session_token=None, prefix: bool = False):
        uid, token = _order_authority(user_id, session_token)
        operator = "LIKE" if prefix else "="
        value = f"{provider}%" if prefix else provider
        with self._connect() as conn, conn.cursor() as cur:
            if os.getenv("RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED", "").lower() in {"1", "true", "yes"}:
                cur.execute("SELECT * FROM public.relay_payment_session_latest_provider_invoice_for_authorized_order(%s::bigint,%s::text,%s::boolean,%s::bigint,%s::text)",
                            (int(order_id), provider, bool(prefix), uid, token))
            else:
                cur.execute("SELECT ps.provider_invoice_id,ps.provider FROM payment_sessions ps "
                            "JOIN orders o ON o.order_id=ps.order_id WHERE ps.order_id=%s "
                            f"AND ps.provider {operator} %s AND ps.provider_invoice_id IS NOT NULL "
                            "AND (o.user_id=%s OR EXISTS(SELECT 1 FROM payment_sessions proof "
                            "WHERE proof.order_id=o.order_id AND proof.session_token=%s)) "
                            "ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1",
                            (int(order_id), value, uid, token))
            row = cur.fetchone()
            return dict(row) if row else None

    def pending_vertu(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT ps.session_token,ps.provider_invoice_id,ps.order_id "
                        "FROM payment_sessions ps JOIN orders o ON o.order_id=ps.order_id "
                        "WHERE ps.provider='vertu' AND ps.status='invoice_created' "
                        "AND ps.provider_invoice_id IS NOT NULL AND o.status='pending' "
                        "AND ps.created_at>now()-interval '2 hours' ORDER BY ps.id LIMIT 100")
            return [dict(row) for row in cur.fetchall()]

    def transition(self, token: str, new_status: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT status FROM payment_sessions WHERE session_token=%s FOR UPDATE",
                        (token,))
            row = cur.fetchone()
            if not row:
                return False
            PaymentStateMachine.transition(row["status"], new_status)
            cur.execute("UPDATE payment_sessions SET status=%s,updated_at=now() "
                        "WHERE session_token=%s AND status=%s",
                        (new_status, token, row["status"]))
            return cur.rowcount == 1

    def active(self):
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT session_token,provider_invoice_id,created_at,expires_at "
                        "FROM payment_sessions WHERE status IN('invoice_created','awaiting_payment')")
            return [dict(row) for row in cur.fetchall()]

    def expire(self, token: str) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("UPDATE payment_sessions SET status='expired',updated_at=now() "
                        "WHERE session_token=%s AND status IN('invoice_created','awaiting_payment')",
                        (token,))
            return cur.rowcount == 1


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLitePaymentSessionStore(sqlite_path)
    if (db_runtime.backend(url) != "postgresql" or
            os.getenv("PAYMENT_SESSION_POSTGRES_ENABLED", "").strip().lower()
            not in {"1", "true", "yes"}):
        raise RuntimeError("postgres_payment_session_store_not_enabled")
    return PostgresPaymentSessionStore(url)
