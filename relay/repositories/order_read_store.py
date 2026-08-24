"""Fixed, read-only views over the canonical buy-order ledger."""
from __future__ import annotations

import os
import sqlite3
from datetime import date, datetime
from decimal import Decimal

from core import db_runtime


_SNAPSHOT_COLUMNS = (
    "order_id,user_id,username,currency,rub_amount,crypto_address,status,created_at,"
    "paid_btc_tx,updated_at,web_user_id,rub_volume_counted,verification_requested,"
    "montera_invoice_id,receipt_deadline,receipt_sent_at,network,agreed_rate,"
    "agreed_crypto_amount,agreed_at"
)


def _value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def _dict(row):
    return {key: _value(value) for key, value in dict(row).items()}


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


class SQLiteOrderReadStore:
    def __init__(self, path: str, *, timeout: float = 5):
        self.path, self.timeout = path, timeout

    def _c(self):
        connection = db_runtime.sqlite_connect(self.path, timeout=self.timeout)
        connection.row_factory = sqlite3.Row
        return connection

    def agreed_quote(self, order_id: int):
        with self._c() as c:
            row = c.execute(
                "SELECT agreed_rate,agreed_crypto_amount FROM orders WHERE order_id=?",
                (int(order_id),),
            ).fetchone()
        if row is None:
            raise LookupError(f"order_not_found:{int(order_id)}")
        return (_value(row["agreed_rate"]), _value(row["agreed_crypto_amount"]))

    def snapshot(self, order_id: int):
        with self._c() as c:
            row = c.execute(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM orders WHERE order_id=?", (int(order_id),)
            ).fetchone()
        return _dict(row) if row else None

    def authorized_snapshot(self, order_id: int, *, user_id=None, session_token=None):
        uid, token = _order_authority(user_id, session_token)
        with self._c() as c:
            row = c.execute(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM orders o WHERE o.order_id=? AND "
                "(o.user_id=? OR EXISTS(SELECT 1 FROM payment_sessions ps "
                "WHERE ps.order_id=o.order_id AND ps.session_token=?)) LIMIT 1",
                (int(order_id), uid, token),).fetchone()
        return _dict(row) if row else None

    def customer_orders(self, user_id: int, *, limit: int = 10, offset: int = 0):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,rub_amount,crypto_address,currency,status,created_at,"
                "paid_btc_tx,network,receipt_sent_at,"
                "(SELECT ps.session_token FROM payment_sessions ps "
                "WHERE ps.order_id=orders.order_id AND ps.session_token IS NOT NULL "
                "AND ps.status NOT IN('failed','expired') "
                "ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1) session_token "
                "FROM orders WHERE user_id=? "
                "ORDER BY created_at DESC,order_id DESC LIMIT ? OFFSET ?",
                (int(user_id), min(100, max(1, int(limit))),
                 min(1_000_000, max(0, int(offset)))),
            ).fetchall()
        return [_dict(row) for row in rows]

    def customer_history(self, user_id: int, *, limit: int = 100):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,created_at,currency,rub_amount,status,crypto_address,"
                "paid_btc_tx,receipt_sent_at FROM orders WHERE user_id=? "
                "ORDER BY order_id DESC LIMIT ?", (int(user_id), min(100, max(1, int(limit))))
            ).fetchall()
        return [_dict(row) for row in rows]

    def latest_customer_order_id(self, user_id: int):
        with self._c() as c:
            row = c.execute(
                "SELECT order_id FROM orders WHERE user_id=? "
                "ORDER BY created_at DESC,order_id DESC LIMIT 1", (int(user_id),)
            ).fetchone()
        return int(row["order_id"]) if row else None

    def find_customer(self, query):
        field = "user_id" if str(query).isdigit() else "username"
        value = int(query) if field == "user_id" else str(query)
        with self._c() as c:
            row = c.execute(
                f"SELECT user_id,username,COUNT(*) total,"
                "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) sent_cnt,"
                "COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) volume "
                f"FROM orders WHERE {field}=?", (value,)
            ).fetchone()
        return _dict(row) if row and row["user_id"] is not None else None

    def web_customer_orders(self, web_user_id: int, user_id: int | None, *, limit: int = 20):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,rub_amount,crypto_address,currency,status,created_at,"
                "paid_btc_tx,network,receipt_sent_at,"
                "(SELECT ps.session_token FROM payment_sessions ps "
                "WHERE ps.order_id=orders.order_id AND ps.session_token IS NOT NULL "
                "AND ps.status NOT IN('failed','expired') "
                "ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1) session_token "
                "FROM orders WHERE web_user_id=? OR (? IS NOT NULL AND user_id=?) "
                "ORDER BY created_at DESC,order_id DESC LIMIT ?",
                (int(web_user_id), user_id, user_id, min(100, max(1, int(limit)))),).fetchall()
        return [_dict(row) for row in rows]

    def receipt_order_ids(self, order_ids):
        ids = [int(order_id) for order_id in order_ids]
        if not ids:
            return set()
        if len(ids) > 100:
            raise ValueError("receipt_order_ids_too_many")
        marks = ",".join("?" for _ in ids)
        with self._c() as c:
            rows = c.execute(
                f"SELECT order_id FROM order_receipts WHERE order_id IN ({marks})", ids
            ).fetchall()
        return {int(row["order_id"]) for row in rows}

    def admin_recent(self, *, limit: int = 20):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,user_id,username,rub_amount,currency,status,created_at "
                "FROM orders ORDER BY created_at DESC,order_id DESC LIMIT ?",
                (min(100, max(1, int(limit))),),
            ).fetchall()
        return [_dict(row) for row in rows]

    def export_recent(self, *, limit: int = 1000):
        with self._c() as c:
            rows = c.execute(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM (SELECT {_SNAPSHOT_COLUMNS} FROM orders "
                "ORDER BY order_id DESC LIMIT ?) recent ORDER BY order_id ASC",
                (min(10_000, max(1, int(limit))),),
            ).fetchall()
        return [_dict(row) for row in rows]

    def customer_aggregates(self, user_id: int):
        with self._c() as c:
            summary = c.execute(
                "SELECT COUNT(*) total,"
                "SUM(CASE WHEN status='sent' THEN 1 ELSE 0 END) completed,"
                "COALESCE(SUM(CASE WHEN status='sent' THEN rub_amount ELSE 0 END),0) volume,"
                "MIN(created_at) first_at FROM orders WHERE user_id=?", (int(user_id),)
            ).fetchone()
            favorite = c.execute(
                "SELECT currency,COUNT(*) count FROM orders WHERE user_id=? AND status='sent' "
                "GROUP BY currency ORDER BY count DESC,currency ASC LIMIT 1", (int(user_id),)
            ).fetchone()
        return {"total": int(summary["total"]), "completed": int(summary["completed"] or 0),
                "volume": _value(summary["volume"] or 0),
                "first_at": _value(summary["first_at"]),
                "favorite_currency": favorite["currency"] if favorite else None}

    def provider_success_count(self, user_id: int) -> int:
        """Legacy provider score: paid plus terminal successful orders."""
        with self._c() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id=? "
                "AND status IN('paid','sent','completed')", (int(user_id),)
            ).fetchone()
        return int(row[0] or 0)

    def creation_limit_state(self, user_id: int, *, daily_since, cooldown_since):
        with self._c() as c:
            row = c.execute(
                "SELECT COUNT(*) daily_count,MAX(created_at) latest_created_at "
                "FROM orders WHERE user_id=? AND created_at>?", (int(user_id), daily_since)
            ).fetchone()
            cooldown = c.execute(
                "SELECT 1 FROM orders WHERE user_id=? "
                "AND datetime(created_at)>datetime(?) LIMIT 1",
                (int(user_id), cooldown_since),).fetchone()
        latest = _value(row["latest_created_at"])
        return {"daily_count": int(row["daily_count"] or 0),
                "cooldown_active": cooldown is not None,
                "latest_created_at": latest}

    def operator_dashboard(self, *, limit: int = 10):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,username,user_id,rub_amount,currency,created_at "
                "FROM orders WHERE status='pending' ORDER BY created_at DESC LIMIT ?",
                (min(100, max(1, int(limit))),),).fetchall()
            paid = c.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()
        return {"pending": [_dict(row) for row in rows], "paid_count": int(paid[0] or 0)}

    def worker_paid_orders(self, *, limit: int = 20):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,rub_amount,crypto_address,currency,created_at "
                "FROM orders WHERE status='paid' ORDER BY created_at ASC LIMIT ?",
                (min(100, max(1, int(limit))),),).fetchall()
        return [_dict(row) for row in rows]

    def active_customer_ids(self, *, days: int = 30, limit: int = 1000):
        with self._c() as c:
            rows = c.execute(
                "SELECT user_id FROM orders WHERE user_id>0 "
                "AND datetime(created_at)>=datetime('now',?) GROUP BY user_id "
                "ORDER BY MAX(created_at) DESC LIMIT ?",
                (f"-{min(365, max(1, int(days)))} days", min(1000, max(1, int(limit))))
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def pending_usdt_match(self, *, sender_address: str, minimum_rub,
                           maximum_rub):
        with self._c() as c:
            row = c.execute(
                "SELECT order_id,user_id,rub_amount,crypto_address,currency FROM orders "
                "WHERE status='pending' AND currency='USDT' AND crypto_address=? "
                "AND rub_amount BETWEEN ? AND ? ORDER BY order_id LIMIT 1",
                (str(sender_address), minimum_rub, maximum_rub),).fetchone()
        return _dict(row) if row else None

    def stuck_pending_ids(self, *, older_than, limit: int = 1000):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id FROM orders WHERE status='pending' "
                "AND datetime(created_at)<datetime(?) "
                "ORDER BY order_id LIMIT ?", (older_than, min(1000, max(1, int(limit))))).fetchall()
        return [int(row["order_id"]) for row in rows]


class PostgresOrderReadStore(SQLiteOrderReadStore):
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _c(self):
        import psycopg
        return psycopg.connect(self.dsn, row_factory=psycopg.rows.dict_row)

    def agreed_quote(self, order_id: int):
        with self._c() as c:
            row = c.execute(
                "SELECT agreed_rate,agreed_crypto_amount FROM orders WHERE order_id=%s",
                (int(order_id),),).fetchone()
        if row is None:
            raise LookupError(f"order_not_found:{int(order_id)}")
        return (_value(row["agreed_rate"]), _value(row["agreed_crypto_amount"]))

    def snapshot(self, order_id: int):
        with self._c() as c:
            row = c.execute(f"SELECT {_SNAPSHOT_COLUMNS} FROM orders WHERE order_id=%s",
                            (int(order_id),)).fetchone()
        return _dict(row) if row else None

    def authorized_snapshot(self, order_id: int, *, user_id=None, session_token=None):
        uid, token = _order_authority(user_id, session_token)
        with self._c() as c:
            if os.getenv("RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED", "").lower() in {"1", "true", "yes"}:
                row = c.execute(
                    "SELECT * FROM public.relay_order_authorized_snapshot(%s::bigint,%s::bigint,%s::text)",
                    (int(order_id), uid, token)).fetchone()
            else:
                row = c.execute(
                    f"SELECT {_SNAPSHOT_COLUMNS} FROM orders o WHERE o.order_id=%s AND "
                    "(o.user_id=%s OR EXISTS(SELECT 1 FROM payment_sessions ps "
                    "WHERE ps.order_id=o.order_id AND ps.session_token=%s)) LIMIT 1",
                    (int(order_id), uid, token),).fetchone()
        return _dict(row) if row else None

    def customer_orders(self, user_id: int, *, limit: int = 10, offset: int = 0):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,rub_amount,crypto_address,currency,status,created_at,"
                "paid_btc_tx,network,receipt_sent_at,"
                "(SELECT ps.session_token FROM payment_sessions ps "
                "WHERE ps.order_id=orders.order_id AND ps.session_token IS NOT NULL "
                "AND ps.status NOT IN('failed','expired') "
                "ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1) session_token "
                "FROM orders WHERE user_id=%s "
                "ORDER BY created_at DESC,order_id DESC LIMIT %s OFFSET %s",
                (int(user_id), min(100, max(1, int(limit))),
                 min(1_000_000, max(0, int(offset)))),).fetchall()
        return [_dict(row) for row in rows]

    def customer_history(self, user_id: int, *, limit: int = 100):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,created_at,currency,rub_amount,status,crypto_address,"
                "paid_btc_tx,receipt_sent_at FROM orders WHERE user_id=%s "
                "ORDER BY order_id DESC LIMIT %s", (int(user_id), min(100, max(1, int(limit))))
            ).fetchall()
        return [_dict(row) for row in rows]

    def latest_customer_order_id(self, user_id: int):
        with self._c() as c:
            row = c.execute(
                "SELECT order_id FROM orders WHERE user_id=%s "
                "ORDER BY created_at DESC,order_id DESC LIMIT 1", (int(user_id),)
            ).fetchone()
        return int(row["order_id"]) if row else None

    def find_customer(self, query):
        field = "user_id" if str(query).isdigit() else "username"
        value = int(query) if field == "user_id" else str(query)
        with self._c() as c:
            row = c.execute(
                f"SELECT user_id,username,COUNT(*) total,"
                "COUNT(*) FILTER(WHERE status='sent') sent_cnt,"
                "COALESCE(SUM(rub_amount) FILTER(WHERE status='sent'),0) volume "
                f"FROM orders WHERE {field}=%s GROUP BY user_id,username", (value,)
            ).fetchone()
        return _dict(row) if row else None

    def web_customer_orders(self, web_user_id: int, user_id: int | None, *, limit: int = 20):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,rub_amount,crypto_address,currency,status,created_at,"
                "paid_btc_tx,network,receipt_sent_at,"
                "(SELECT ps.session_token FROM payment_sessions ps "
                "WHERE ps.order_id=orders.order_id AND ps.session_token IS NOT NULL "
                "AND ps.status NOT IN('failed','expired') "
                "ORDER BY ps.created_at DESC,ps.id DESC LIMIT 1) session_token "
                "FROM orders WHERE web_user_id=%s OR user_id=%s "
                "ORDER BY created_at DESC,order_id DESC LIMIT %s",
                (int(web_user_id), user_id, min(100, max(1, int(limit)))),).fetchall()
        return [_dict(row) for row in rows]

    def receipt_order_ids(self, order_ids):
        ids = [int(order_id) for order_id in order_ids]
        if not ids:
            return set()
        if len(ids) > 100:
            raise ValueError("receipt_order_ids_too_many")
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id FROM order_receipts WHERE order_id=ANY(%s)", (ids,)
            ).fetchall()
        return {int(row["order_id"]) for row in rows}

    def admin_recent(self, *, limit: int = 20):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,user_id,username,rub_amount,currency,status,created_at "
                "FROM orders ORDER BY created_at DESC,order_id DESC LIMIT %s",
                (min(100, max(1, int(limit))),),).fetchall()
        return [_dict(row) for row in rows]

    def export_recent(self, *, limit: int = 1000):
        with self._c() as c:
            rows = c.execute(
                f"SELECT {_SNAPSHOT_COLUMNS} FROM (SELECT {_SNAPSHOT_COLUMNS} FROM orders "
                "ORDER BY order_id DESC LIMIT %s) recent ORDER BY order_id ASC",
                (min(10_000, max(1, int(limit))),),).fetchall()
        return [_dict(row) for row in rows]

    def customer_aggregates(self, user_id: int):
        with self._c() as c:
            summary = c.execute(
                "SELECT COUNT(*) total,COUNT(*) FILTER(WHERE status='sent') completed,"
                "COALESCE(SUM(rub_amount) FILTER(WHERE status='sent'),0) volume,"
                "MIN(created_at) first_at FROM orders WHERE user_id=%s", (int(user_id),)
            ).fetchone()
            favorite = c.execute(
                "SELECT currency,COUNT(*) count FROM orders WHERE user_id=%s AND status='sent' "
                "GROUP BY currency ORDER BY count DESC,currency ASC LIMIT 1", (int(user_id),)
            ).fetchone()
        return {"total": int(summary["total"]), "completed": int(summary["completed"]),
                "volume": _value(summary["volume"]), "first_at": _value(summary["first_at"]),
                "favorite_currency": favorite["currency"] if favorite else None}

    def provider_success_count(self, user_id: int) -> int:
        with self._c() as c:
            row = c.execute(
                "SELECT COUNT(*) FROM orders WHERE user_id=%s "
                "AND status=ANY(%s)", (int(user_id), ["paid", "sent", "completed"])
            ).fetchone()
        return int(row["count"] or 0)

    def creation_limit_state(self, user_id: int, *, daily_since, cooldown_since):
        with self._c() as c:
            row = c.execute(
                "SELECT COUNT(*) daily_count,MAX(created_at) latest_created_at "
                "FROM orders WHERE user_id=%s AND created_at>%s",
                (int(user_id), daily_since),).fetchone()
            cooldown = c.execute(
                "SELECT 1 FROM orders WHERE user_id=%s AND created_at>%s LIMIT 1",
                (int(user_id), cooldown_since),).fetchone()
        latest = _value(row["latest_created_at"])
        return {"daily_count": int(row["daily_count"] or 0),
                "cooldown_active": cooldown is not None,
                "latest_created_at": latest}

    def operator_dashboard(self, *, limit: int = 10):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,username,user_id,rub_amount,currency,created_at "
                "FROM orders WHERE status='pending' ORDER BY created_at DESC LIMIT %s",
                (min(100, max(1, int(limit))),),).fetchall()
            paid = c.execute("SELECT COUNT(*) FROM orders WHERE status='paid'").fetchone()
        return {"pending": [_dict(row) for row in rows],
                "paid_count": int(paid["count"] or 0)}

    def worker_paid_orders(self, *, limit: int = 20):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id,rub_amount,crypto_address,currency,created_at "
                "FROM orders WHERE status='paid' ORDER BY created_at ASC LIMIT %s",
                (min(100, max(1, int(limit))),),).fetchall()
        return [_dict(row) for row in rows]

    def active_customer_ids(self, *, days: int = 30, limit: int = 1000):
        with self._c() as c:
            rows = c.execute(
                "SELECT user_id FROM orders WHERE user_id>0 "
                "AND created_at>=now()-(%s*interval '1 day') GROUP BY user_id "
                "ORDER BY MAX(created_at) DESC LIMIT %s",
                (min(365, max(1, int(days))), min(1000, max(1, int(limit))))
            ).fetchall()
        return [int(row["user_id"]) for row in rows]

    def pending_usdt_match(self, *, sender_address: str, minimum_rub,
                           maximum_rub):
        with self._c() as c:
            row = c.execute(
                "SELECT order_id,user_id,rub_amount,crypto_address,currency FROM orders "
                "WHERE status='pending' AND currency='USDT' AND crypto_address=%s "
                "AND rub_amount BETWEEN %s AND %s ORDER BY order_id LIMIT 1",
                (str(sender_address), minimum_rub, maximum_rub),).fetchone()
        return _dict(row) if row else None

    def stuck_pending_ids(self, *, older_than, limit: int = 1000):
        with self._c() as c:
            rows = c.execute(
                "SELECT order_id FROM orders WHERE status='pending' AND created_at<%s "
                "ORDER BY order_id LIMIT %s", (older_than, min(1000, max(1, int(limit))))).fetchall()
        return [int(row["order_id"]) for row in rows]


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteOrderReadStore(sqlite_path)
    if (db_runtime.backend(url) != "postgresql" or
            os.getenv("ORDER_READ_POSTGRES_ENABLED", "").lower() not in {"1", "true", "yes"}):
        raise RuntimeError("postgres_order_read_store_not_enabled")
    return PostgresOrderReadStore(url)
