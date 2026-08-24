"""Atomic candidate selection and durable delivery jobs for bot reminders."""
from __future__ import annotations

import json
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from core import db_runtime


KINDS = {
    "recall",
    "montera_customer",
    "montera_admin",
    "pay_reminder",
    "payout_delayed",
    "winback_promo",
}
_JOB_COLUMNS = "id,kind,dedupe_key,payload,attempts"
def _utc(value: datetime | None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _sqlite_time(value: datetime) -> str:
    return _utc(value).strftime("%Y-%m-%d %H:%M:%S")


def _json_value(value):
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, datetime):
        return _utc(value).isoformat()
    return value


def _payload(**values) -> str:
    return json.dumps(
        {key: _json_value(value) for key, value in values.items()},
        ensure_ascii=False,
        separators=(",", ":"),
    )


def _limit(value: int, maximum: int = 1000) -> int:
    return max(1, min(int(value), maximum))


def _decode_job(row):
    if row is None:
        return None
    item = dict(row)
    if isinstance(item["payload"], str):
        item["payload"] = json.loads(item["payload"])
    return item


def _winback_code(discount) -> str:
    return f"BACK{int(float(discount))}-{secrets.token_hex(3).upper()}"


class SQLiteBotNotificationStore:
    def __init__(self, path: str, *, timeout: float = 10):
        self.path, self.timeout = path, timeout

    def _c(self):
        conn = db_runtime.sqlite_connect(self.path, timeout=self.timeout)
        conn.row_factory = sqlite3.Row
        return conn

    @staticmethod
    def _mark(conn, key, event) -> bool:
        return conn.execute(
            "INSERT OR IGNORE INTO sent_notifications(order_id,event) VALUES(?,?)",
            (int(key), event),
        ).rowcount == 1

    @staticmethod
    def _job(conn, kind, key, payload) -> None:
        changed = conn.execute(
            "INSERT OR IGNORE INTO bot_notification_jobs(kind,dedupe_key,payload) "
            "VALUES(?,?,?)",
            (kind, str(key), payload),
        ).rowcount
        if changed != 1:
            raise RuntimeError("bot_notification_job_conflict")

    def queue_due_recalls(self, *, now: datetime | None = None, limit: int = 200) -> int:
        """Claim sent customers with no order for 14 days, once per lifetime."""
        threshold = _sqlite_time(_utc(now) - timedelta(days=14))
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT DISTINCT o.user_id FROM orders o "
                "WHERE o.user_id>0 AND o.status='sent' "
                "AND NOT EXISTS(SELECT 1 FROM orders recent "
                " WHERE recent.user_id=o.user_id AND datetime(recent.created_at)>datetime(?)) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.user_id AND sn.event='recall') "
                "ORDER BY o.user_id LIMIT ?",
                (threshold, _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                user_id = int(row["user_id"])
                if not self._mark(conn, user_id, "recall"):
                    continue
                self._job(conn, "recall", user_id, _payload(user_id=user_id))
                queued += 1
            conn.commit()
            return queued

    def queue_due_montera(self, *, now: datetime | None = None, limit: int = 200) -> int:
        """Snapshot Montera receipt state and create independent audience jobs."""
        current = _utc(now)
        window_from = _sqlite_time(current + timedelta(minutes=8))
        window_to = _sqlite_time(current + timedelta(minutes=12))
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.montera_invoice_id,"
                "EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) has_file "
                "FROM orders o WHERE o.user_id>0 AND o.status='pending' "
                "AND o.receipt_sent_at IS NULL "
                "AND datetime(o.receipt_deadline) BETWEEN datetime(?) AND datetime(?) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.order_id AND sn.event='receipt_reminder') "
                "ORDER BY o.order_id LIMIT ?",
                (window_from, window_to, _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id, user_id = int(row["order_id"]), int(row["user_id"])
                if not self._mark(conn, order_id, "receipt_reminder"):
                    continue
                payload = _payload(
                    order_id=order_id,
                    user_id=user_id,
                    invoice_id=row["montera_invoice_id"],
                    has_file=bool(row["has_file"]),
                )
                self._job(conn, "montera_customer", order_id, payload)
                self._job(conn, "montera_admin", order_id, payload)
                queued += 1
            conn.commit()
            return queued

    def queue_due_abandoned(self, *, now: datetime | None = None, limit: int = 200) -> int:
        current = _utc(now)
        window_from = _sqlite_time(current - timedelta(minutes=13))
        window_to = _sqlite_time(current - timedelta(minutes=8))
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.rub_amount,o.currency,"
                "(SELECT ps.session_token FROM payment_sessions ps "
                " WHERE ps.order_id=o.order_id AND ps.status NOT IN('failed','expired') "
                " ORDER BY ps.id DESC LIMIT 1) session_token "
                "FROM orders o WHERE o.user_id>0 AND o.status='pending' "
                "AND datetime(o.created_at) BETWEEN datetime(?) AND datetime(?) "
                "AND NOT EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.order_id AND sn.event='pay_reminder') "
                "ORDER BY o.order_id LIMIT ?",
                (window_from, window_to, _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id = int(row["order_id"])
                if not self._mark(conn, order_id, "pay_reminder"):
                    continue
                self._job(
                    conn,
                    "pay_reminder",
                    order_id,
                    _payload(
                        order_id=order_id,
                        user_id=int(row["user_id"]),
                        rub_amount=row["rub_amount"],
                        currency=row["currency"],
                        session_token=row["session_token"],
                    ),
                )
                queued += 1
            conn.commit()
            return queued

    def queue_due_payout_delays(
        self,
        *,
        warn_minutes: int,
        now: datetime | None = None,
        limit: int = 30,
    ) -> int:
        threshold = _sqlite_time(_utc(now) - timedelta(minutes=max(0, int(warn_minutes))))
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.currency FROM orders o "
                "WHERE o.user_id>0 AND o.status='paid' AND COALESCE(o.paid_btc_tx,'')='' "
                "AND (datetime(COALESCE(NULLIF(o.updated_at,''),o.created_at)) IS NULL "
                " OR datetime(COALESCE(NULLIF(o.updated_at,''),o.created_at))<=datetime(?)) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.order_id AND sn.event='payout_delayed') "
                "ORDER BY datetime(COALESCE(NULLIF(o.updated_at,''),o.created_at)) IS NOT NULL,"
                "datetime(COALESCE(NULLIF(o.updated_at,''),o.created_at)),o.order_id LIMIT ?",
                (threshold, _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id = int(row["order_id"])
                if not self._mark(conn, order_id, "payout_delayed"):
                    continue
                self._job(
                    conn,
                    "payout_delayed",
                    order_id,
                    _payload(
                        order_id=order_id,
                        user_id=int(row["user_id"]),
                        currency=row["currency"],
                    ),
                )
                queued += 1
            conn.commit()
            return queued

    def queue_due_winbacks(
        self,
        *,
        discount,
        valid_hours: int,
        now: datetime | None = None,
        limit: int = 20,
    ) -> int:
        current = _utc(now)
        window_from = _sqlite_time(current - timedelta(hours=48))
        window_to = _sqlite_time(current - timedelta(hours=1))
        valid_until = _sqlite_time(current + timedelta(hours=int(valid_hours)))
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                "SELECT MAX(o.order_id) order_id,o.user_id FROM orders o "
                "WHERE o.user_id>0 AND o.status='expired' "
                "AND datetime(o.updated_at) BETWEEN datetime(?) AND datetime(?) "
                "AND NOT EXISTS(SELECT 1 FROM orders paid WHERE paid.user_id=o.user_id "
                " AND paid.status IN('paid','sent')) "
                "AND NOT EXISTS(SELECT 1 FROM order_receipts r JOIN orders receipt_order "
                " ON receipt_order.order_id=r.order_id WHERE receipt_order.user_id=o.user_id) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn JOIN orders marked "
                " ON marked.order_id=sn.order_id WHERE marked.user_id=o.user_id "
                " AND sn.event='winback_promo') "
                "AND NOT EXISTS(SELECT 1 FROM blocked_users b WHERE b.user_id=o.user_id) "
                "GROUP BY o.user_id ORDER BY o.user_id LIMIT ?",
                (window_from, window_to, _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id, user_id = int(row["order_id"]), int(row["user_id"])
                if not self._mark(conn, order_id, "winback_promo"):
                    continue
                code = _winback_code(discount)
                promo = conn.execute(
                    "INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until,is_active) "
                    "VALUES(?,?,1,?,1)",
                    (code, discount, valid_until),
                )
                self._job(
                    conn,
                    "winback_promo",
                    order_id,
                    _payload(
                        order_id=order_id,
                        user_id=user_id,
                        code=code,
                        code_id=int(promo.lastrowid),
                        discount=discount,
                        valid_hours=int(valid_hours),
                        valid_until=valid_until,
                    ),
                )
                queued += 1
            conn.commit()
            return queued

    # Single-candidate methods remain useful to callers that already own a fixed
    # selection boundary. They use the same marker/job transaction.
    def queue_recall(self, user_id) -> bool:
        return self._one("recall", user_id, "recall", user_id=int(user_id))

    def queue_montera(self, *, order_id, user_id, invoice_id, has_file) -> bool:
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._mark(conn, order_id, "receipt_reminder"):
                conn.commit()
                return False
            payload = _payload(
                order_id=int(order_id),
                user_id=int(user_id),
                invoice_id=invoice_id,
                has_file=bool(has_file),
            )
            self._job(conn, "montera_customer", order_id, payload)
            self._job(conn, "montera_admin", order_id, payload)
            conn.commit()
            return True

    def queue_abandoned(self, *, order_id, user_id, rub_amount, currency, session_token=None):
        return self._one(
            "pay_reminder",
            order_id,
            "pay_reminder",
            order_id=int(order_id),
            user_id=int(user_id),
            rub_amount=rub_amount,
            currency=currency,
            session_token=session_token,
        )

    def queue_payout_delay(self, *, order_id, user_id, currency):
        return self._one(
            "payout_delayed",
            order_id,
            "payout_delayed",
            order_id=int(order_id),
            user_id=int(user_id),
            currency=currency,
        )

    def _one(self, kind, key, event, **payload) -> bool:
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._mark(conn, key, event):
                conn.commit()
                return False
            self._job(conn, kind, key, _payload(**payload))
            conn.commit()
            return True

    def queue_winback(self, *, order_id, user_id, code, discount, valid_until, valid_hours=72):
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if not self._mark(conn, order_id, "winback_promo"):
                conn.commit()
                return False
            promo = conn.execute(
                "INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until,is_active) "
                "VALUES(?,?,1,?,1)",
                (code, discount, valid_until),
            )
            self._job(
                conn,
                "winback_promo",
                order_id,
                _payload(
                    order_id=int(order_id),
                    user_id=int(user_id),
                    code=code,
                    code_id=int(promo.lastrowid),
                    discount=discount,
                    valid_hours=int(valid_hours),
                    valid_until=valid_until,
                ),
            )
            conn.commit()
            return True

    def claim_notification(self, *, kind: str | None = None):
        if kind is not None and kind not in KINDS:
            raise ValueError("invalid_bot_notification_kind")
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if kind is None:
                row = conn.execute(
                    "SELECT id FROM bot_notification_jobs WHERE state='pending' "
                    "ORDER BY attempts,id LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM bot_notification_jobs WHERE state='pending' AND kind=? "
                    "ORDER BY attempts,id LIMIT 1",
                    (kind,),
                ).fetchone()
            if not row:
                conn.commit()
                return None
            item = conn.execute(
                "UPDATE bot_notification_jobs SET state='sending',attempts=attempts+1,"
                "claimed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
                "WHERE id=? AND state='pending' RETURNING " + _JOB_COLUMNS,
                (int(row["id"]),),
            ).fetchone()
            if not item:
                raise RuntimeError("bot_notification_claim_lost")
            conn.commit()
            return _decode_job(item)

    def mark_notification_sent(self, ident: int) -> bool:
        return self._state(ident, sent=True)

    def retry_notification(self, ident: int) -> bool:
        return self._state(ident, sent=False)

    def _state(self, ident: int, *, sent: bool) -> bool:
        with self._c() as conn:
            if sent:
                changed = conn.execute(
                    "UPDATE bot_notification_jobs SET state='sent',sent_at=CURRENT_TIMESTAMP,"
                    "updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='sending'",
                    (int(ident),),
                ).rowcount
            else:
                changed = conn.execute(
                    "UPDATE bot_notification_jobs SET state='pending',claimed_at=NULL,"
                    "updated_at=CURRENT_TIMESTAMP WHERE id=? AND state='sending'",
                    (int(ident),),
                ).rowcount
            conn.commit()
            return changed == 1

    # Backward-compatible names used by the initial repository contracts.
    def claim(self, kind=None):
        return self.claim_notification(kind=kind)

    def sent(self, ident):
        return self.mark_notification_sent(ident)

    def retry(self, ident):
        return self.retry_notification(ident)


class PostgresBotNotificationStore(SQLiteBotNotificationStore):
    def __init__(self, dsn: str):
        self.dsn = dsn

    def _c(self):
        import psycopg

        return psycopg.connect(self.dsn, row_factory=psycopg.rows.dict_row)

    @staticmethod
    def _mark(conn, key, event) -> bool:
        return conn.execute(
            "INSERT INTO sent_notifications(order_id,event) VALUES(%s,%s) "
            "ON CONFLICT DO NOTHING RETURNING order_id",
            (int(key), event),
        ).fetchone() is not None

    @staticmethod
    def _job(conn, kind, key, payload) -> None:
        row = conn.execute(
            "INSERT INTO bot_notification_jobs(kind,dedupe_key,payload) VALUES(%s,%s,%s::jsonb) "
            "ON CONFLICT DO NOTHING RETURNING id",
            (kind, str(key), payload),
        ).fetchone()
        if row is None:
            raise RuntimeError("bot_notification_job_conflict")

    def queue_due_recalls(self, *, now: datetime | None = None, limit: int = 200) -> int:
        threshold = _utc(now) - timedelta(days=14)
        with self._c() as conn:
            rows = conn.execute(
                "SELECT DISTINCT o.user_id FROM orders o "
                "WHERE o.user_id>0 AND o.status='sent' "
                "AND NOT EXISTS(SELECT 1 FROM orders recent "
                " WHERE recent.user_id=o.user_id AND recent.created_at>%s) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.user_id AND sn.event='recall') "
                "ORDER BY o.user_id LIMIT %s",
                (threshold, _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                user_id = int(row["user_id"])
                if not self._mark(conn, user_id, "recall"):
                    continue
                self._job(conn, "recall", user_id, _payload(user_id=user_id))
                queued += 1
            return queued

    def queue_due_montera(self, *, now: datetime | None = None, limit: int = 200) -> int:
        current = _utc(now)
        with self._c() as conn:
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.montera_invoice_id,"
                "EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) has_file "
                "FROM orders o WHERE o.user_id>0 AND o.status='pending' "
                "AND o.receipt_sent_at IS NULL AND o.receipt_deadline BETWEEN %s AND %s "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.order_id AND sn.event='receipt_reminder') "
                "ORDER BY o.order_id FOR UPDATE OF o SKIP LOCKED LIMIT %s",
                (current + timedelta(minutes=8), current + timedelta(minutes=12), _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id, user_id = int(row["order_id"]), int(row["user_id"])
                if not self._mark(conn, order_id, "receipt_reminder"):
                    continue
                payload = _payload(
                    order_id=order_id,
                    user_id=user_id,
                    invoice_id=row["montera_invoice_id"],
                    has_file=bool(row["has_file"]),
                )
                self._job(conn, "montera_customer", order_id, payload)
                self._job(conn, "montera_admin", order_id, payload)
                queued += 1
            return queued

    def queue_due_abandoned(self, *, now: datetime | None = None, limit: int = 200) -> int:
        current = _utc(now)
        with self._c() as conn:
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.rub_amount,o.currency,"
                "(SELECT ps.session_token FROM payment_sessions ps "
                " WHERE ps.order_id=o.order_id AND ps.status NOT IN('failed','expired') "
                " ORDER BY ps.id DESC LIMIT 1) session_token "
                "FROM orders o WHERE o.user_id>0 AND o.status='pending' "
                "AND o.created_at BETWEEN %s AND %s "
                "AND NOT EXISTS(SELECT 1 FROM order_receipts r WHERE r.order_id=o.order_id) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.order_id AND sn.event='pay_reminder') "
                "ORDER BY o.order_id FOR UPDATE OF o SKIP LOCKED LIMIT %s",
                (current - timedelta(minutes=13), current - timedelta(minutes=8), _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id = int(row["order_id"])
                if not self._mark(conn, order_id, "pay_reminder"):
                    continue
                self._job(
                    conn,
                    "pay_reminder",
                    order_id,
                    _payload(
                        order_id=order_id,
                        user_id=int(row["user_id"]),
                        rub_amount=row["rub_amount"],
                        currency=row["currency"],
                        session_token=row["session_token"],
                    ),
                )
                queued += 1
            return queued

    def queue_due_payout_delays(
        self,
        *,
        warn_minutes: int,
        now: datetime | None = None,
        limit: int = 30,
    ) -> int:
        threshold = _utc(now) - timedelta(minutes=max(0, int(warn_minutes)))
        with self._c() as conn:
            rows = conn.execute(
                "SELECT o.order_id,o.user_id,o.currency FROM orders o "
                "WHERE o.user_id>0 AND o.status='paid' AND COALESCE(o.paid_btc_tx,'')='' "
                "AND COALESCE(o.updated_at,o.created_at)<=%s "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn "
                " WHERE sn.order_id=o.order_id AND sn.event='payout_delayed') "
                "ORDER BY COALESCE(o.updated_at,o.created_at),o.order_id "
                "FOR UPDATE OF o SKIP LOCKED LIMIT %s",
                (threshold, _limit(limit)),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id = int(row["order_id"])
                if not self._mark(conn, order_id, "payout_delayed"):
                    continue
                self._job(
                    conn,
                    "payout_delayed",
                    order_id,
                    _payload(
                        order_id=order_id,
                        user_id=int(row["user_id"]),
                        currency=row["currency"],
                    ),
                )
                queued += 1
            return queued

    def queue_due_winbacks(
        self,
        *,
        discount,
        valid_hours: int,
        now: datetime | None = None,
        limit: int = 20,
    ) -> int:
        current = _utc(now)
        valid_until = current + timedelta(hours=int(valid_hours))
        with self._c() as conn:
            rows = conn.execute(
                "SELECT MAX(o.order_id) order_id,o.user_id FROM orders o "
                "WHERE o.user_id>0 AND o.status='expired' "
                "AND o.updated_at BETWEEN %s AND %s "
                "AND NOT EXISTS(SELECT 1 FROM orders paid WHERE paid.user_id=o.user_id "
                " AND paid.status=ANY(%s)) "
                "AND NOT EXISTS(SELECT 1 FROM order_receipts r JOIN orders receipt_order "
                " ON receipt_order.order_id=r.order_id WHERE receipt_order.user_id=o.user_id) "
                "AND NOT EXISTS(SELECT 1 FROM sent_notifications sn JOIN orders marked "
                " ON marked.order_id=sn.order_id WHERE marked.user_id=o.user_id "
                " AND sn.event='winback_promo') "
                "AND NOT EXISTS(SELECT 1 FROM blocked_users b WHERE b.user_id=o.user_id) "
                "GROUP BY o.user_id ORDER BY o.user_id LIMIT %s",
                (
                    current - timedelta(hours=48),
                    current - timedelta(hours=1),
                    ["paid", "sent"],
                    _limit(limit),
                ),
            ).fetchall()
            queued = 0
            for row in rows:
                order_id, user_id = int(row["order_id"]), int(row["user_id"])
                # The marker is the concurrency claim. A later expired order for
                # the same user is still excluded by the cross-user marker query.
                if not self._mark(conn, order_id, "winback_promo"):
                    continue
                code = _winback_code(discount)
                promo_id = conn.execute(
                    "INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until,is_active) "
                    "VALUES(%s,%s,1,%s,true) RETURNING id",
                    (code, discount, valid_until),
                ).fetchone()["id"]
                self._job(
                    conn,
                    "winback_promo",
                    order_id,
                    _payload(
                        order_id=order_id,
                        user_id=user_id,
                        code=code,
                        code_id=int(promo_id),
                        discount=discount,
                        valid_hours=int(valid_hours),
                        valid_until=valid_until,
                    ),
                )
                queued += 1
            return queued

    def queue_montera(self, *, order_id, user_id, invoice_id, has_file) -> bool:
        with self._c() as conn:
            if not self._mark(conn, order_id, "receipt_reminder"):
                return False
            payload = _payload(
                order_id=int(order_id),
                user_id=int(user_id),
                invoice_id=invoice_id,
                has_file=bool(has_file),
            )
            self._job(conn, "montera_customer", order_id, payload)
            self._job(conn, "montera_admin", order_id, payload)
            return True

    def _one(self, kind, key, event, **payload) -> bool:
        with self._c() as conn:
            if not self._mark(conn, key, event):
                return False
            self._job(conn, kind, key, _payload(**payload))
            return True

    def queue_winback(self, *, order_id, user_id, code, discount, valid_until, valid_hours=72):
        with self._c() as conn:
            if not self._mark(conn, order_id, "winback_promo"):
                return False
            promo_id = conn.execute(
                "INSERT INTO promo_codes(code,discount_percent,max_uses,valid_until,is_active) "
                "VALUES(%s,%s,1,%s,true) RETURNING id",
                (code, discount, valid_until),
            ).fetchone()["id"]
            self._job(
                conn,
                "winback_promo",
                order_id,
                _payload(
                    order_id=int(order_id),
                    user_id=int(user_id),
                    code=code,
                    code_id=int(promo_id),
                    discount=discount,
                    valid_hours=int(valid_hours),
                    valid_until=valid_until,
                ),
            )
            return True

    def claim_notification(self, *, kind: str | None = None):
        if kind is not None and kind not in KINDS:
            raise ValueError("invalid_bot_notification_kind")
        with self._c() as conn:
            if kind is None:
                row = conn.execute(
                    "SELECT id FROM bot_notification_jobs WHERE state='pending' "
                    "ORDER BY attempts,id FOR UPDATE SKIP LOCKED LIMIT 1"
                ).fetchone()
            else:
                row = conn.execute(
                    "SELECT id FROM bot_notification_jobs WHERE state='pending' AND kind=%s "
                    "ORDER BY attempts,id FOR UPDATE SKIP LOCKED LIMIT 1",
                    (kind,),
                ).fetchone()
            if not row:
                return None
            item = conn.execute(
                "UPDATE bot_notification_jobs SET state='sending',attempts=attempts+1,"
                "claimed_at=now(),updated_at=now() WHERE id=%s AND state='pending' "
                "RETURNING " + _JOB_COLUMNS,
                (int(row["id"]),),
            ).fetchone()
            if not item:
                raise RuntimeError("bot_notification_claim_lost")
            return _decode_job(item)

    def _state(self, ident: int, *, sent: bool) -> bool:
        with self._c() as conn:
            if sent:
                changed = conn.execute(
                    "UPDATE bot_notification_jobs SET state='sent',sent_at=now(),updated_at=now() "
                    "WHERE id=%s AND state='sending'",
                    (int(ident),),
                ).rowcount
            else:
                changed = conn.execute(
                    "UPDATE bot_notification_jobs SET state='pending',claimed_at=NULL,updated_at=now() "
                    "WHERE id=%s AND state='sending'",
                    (int(ident),),
                ).rowcount
            return changed == 1


class PostgresB5BotNotificationStore(PostgresBotNotificationStore):
    """Execute-only B5.3 adapter; selected explicitly after function migration."""

    def _scalar(self, sql: str, args) -> object:
        with self._c() as conn:
            row = conn.execute(sql, args).fetchone()
            if row is None or "result" not in row:
                raise RuntimeError("bot_notification_function_result_missing")
            return row["result"]

    def queue_due_recalls(self, *, now: datetime | None = None, limit: int = 200) -> int:
        return int(self._scalar(
            "SELECT public.bot_b5_queue_due_recalls(%s,%s) AS result",
            (_utc(now), _limit(limit)),
        ))

    def queue_due_montera(self, *, now: datetime | None = None, limit: int = 200) -> int:
        return int(self._scalar(
            "SELECT public.bot_b5_queue_due_montera(%s,%s) AS result",
            (_utc(now), _limit(limit)),
        ))

    def queue_due_abandoned(self, *, now: datetime | None = None, limit: int = 200) -> int:
        return int(self._scalar(
            "SELECT public.bot_b5_queue_due_abandoned(%s,%s) AS result",
            (_utc(now), _limit(limit)),
        ))

    def queue_due_payout_delays(
        self,
        *,
        warn_minutes: int,
        now: datetime | None = None,
        limit: int = 30,
    ) -> int:
        return int(self._scalar(
            "SELECT public.bot_b5_queue_due_payout_delays(%s,%s,%s) AS result",
            (int(warn_minutes), _utc(now), _limit(limit)),
        ))

    def queue_due_winbacks(
        self,
        *,
        discount,
        valid_hours: int,
        now: datetime | None = None,
        limit: int = 20,
    ) -> int:
        return int(self._scalar(
            "SELECT public.bot_b5_queue_due_winbacks(%s,%s,%s,%s) AS result",
            (discount, int(valid_hours), _utc(now), _limit(limit)),
        ))

    def claim_notification(self, *, kind: str | None = None):
        if kind is not None and kind not in KINDS:
            raise ValueError("invalid_bot_notification_kind")
        with self._c() as conn:
            row = conn.execute(
                "SELECT id,kind,dedupe_key,payload,attempts "
                "FROM public.bot_b5_notification_claim(%s)",
                (kind,),
            ).fetchone()
            return _decode_job(row)

    def mark_notification_sent(self, ident: int) -> bool:
        return bool(self._scalar(
            "SELECT public.bot_b5_notification_mark_sent(%s) AS result",
            (int(ident),),
        ))

    def retry_notification(self, ident: int) -> bool:
        # The dispatcher may call this only for an explicit provider rejection
        # before any recipient accepted delivery. Ambiguous transport outcomes
        # remain claimed for operator reconciliation.
        return bool(self._scalar(
            "SELECT public.bot_b5_notification_retry(%s) AS result",
            (int(ident),),
        ))

    @staticmethod
    def _legacy_direct_enqueue_disabled(*_args, **_kwargs):
        raise RuntimeError("bot_notification_direct_enqueue_disabled_in_b5_acl_mode")

    queue_recall = _legacy_direct_enqueue_disabled
    queue_montera = _legacy_direct_enqueue_disabled
    queue_abandoned = _legacy_direct_enqueue_disabled
    queue_payout_delay = _legacy_direct_enqueue_disabled
    queue_winback = _legacy_direct_enqueue_disabled


class PostgresB53HardenedBotNotificationStore(PostgresB5BotNotificationStore):
    """Default-off 058-062 adapter with attested producer/delivery/transport identities."""

    hardened_delivery = True

    def __init__(self, background_dsn: str, delivery_dsn: str, transport_dsn: str):
        super().__init__(background_dsn)
        self.delivery_dsn = delivery_dsn
        self.transport_dsn = transport_dsn
        self.preflight()

    @staticmethod
    def _connect(dsn: str):
        import psycopg
        return psycopg.connect(dsn, row_factory=psycopg.rows.dict_row)

    @staticmethod
    def _attest_connection(conn, lane: str):
        expected = f"obsidian_exchange_bot_{lane}"
        row = conn.execute(
            "SELECT session_user AS session_name,current_user AS current_name,r.rolcanlogin,"
            "r.rolinherit,r.rolsuper,r.rolcreaterole,r.rolcreatedb,r.rolreplication,r.rolbypassrls,"
            "(SELECT count(*) FROM pg_catalog.pg_auth_members m WHERE m.member=r.oid) AS memberships "
            "FROM pg_catalog.pg_roles r WHERE r.rolname=session_user"
        ).fetchone()
        if not row or row["session_name"] != expected or row["current_name"] != expected:
            raise RuntimeError(f"bot_notification_identity_preflight_failed:{lane}:principal")
        if (not row["rolcanlogin"] or row["rolinherit"] or row["rolsuper"]
                or row["rolcreaterole"] or row["rolcreatedb"] or row["rolreplication"]
                or row["rolbypassrls"] or int(row["memberships"]) != 0):
            raise RuntimeError(f"bot_notification_identity_preflight_failed:{lane}:role_attributes")
        PostgresB53HardenedBotNotificationStore._attest_manifest(conn, lane, expected)

    @staticmethod
    def _attest_manifest(conn, lane: str, expected: str):
        manifests = {
            "background": {
                "bot_b59_queue_due_recalls(integer)", "bot_b59_queue_due_montera(integer)",
                "bot_b59_queue_due_abandoned(integer)", "bot_b59_queue_due_payout_delays(integer)",
                "bot_b59_queue_due_winbacks(integer)",
            },
            "delivery": {
                "bot_b53_delivery_claim(text)", "bot_b53_delivery_retry_pre_submit(bigint,uuid,uuid)",
                "bot_b53_delivery_mark_manual(bigint,uuid,uuid)",
                "bot_b61_delivery_pre_submit(bigint,uuid,uuid)",
                "bot_b61_delivery_mark_local_manual(bigint,uuid,text,text)",
                "bot_b62_consume_accepted(bigint,uuid,uuid)",
            },
            "transport": {
                "bot_b62_transport_record_evidence(bigint,uuid,uuid,text,text,text,text,text,timestamp with time zone)",
            },
        }
        owners = {"background": "obsidian_exchange_bot_background_owner",
                  "delivery": "obsidian_exchange_bot_delivery_owner",
                  "transport": "obsidian_exchange_bot_transport_owner"}
        combined = set().union(*manifests.values())
        for signature in sorted(combined):
            owner_expected = ("obsidian_exchange_bot_notification_reconciler_owner"
                              if signature.startswith("bot_b62_consume_accepted") else
                              owners[next(name for name, values in manifests.items()
                                          if signature in values)])
            row = conn.execute(
                "SELECT p.prosecdef,pg_catalog.pg_get_userbyid(p.proowner) AS owner,p.proconfig,"
                "pg_catalog.has_function_privilege(session_user,p.oid,'EXECUTE') AS allowed,"
                "pg_catalog.has_function_privilege('public',p.oid,'EXECUTE') AS public_allowed "
                "FROM pg_catalog.pg_proc p WHERE p.oid=pg_catalog.to_regprocedure(%s)",
                ("public." + signature,),
            ).fetchone()
            should_allow = signature in manifests[lane]
            if (not row or bool(row["allowed"]) != should_allow or row["public_allowed"]
                    or not row["prosecdef"] or row["owner"] != owner_expected
                    or "search_path=pg_catalog" not in (row["proconfig"] or [])):
                raise RuntimeError(f"bot_notification_identity_preflight_failed:{lane}:function_manifest")
        grants = conn.execute(
            "SELECT (SELECT count(*) FROM information_schema.role_table_grants WHERE grantee=%s),"
            "(SELECT count(*) FROM information_schema.column_privileges WHERE grantee=%s),"
            "(SELECT count(*) FROM information_schema.role_usage_grants WHERE grantee=%s AND object_type='SEQUENCE')",
            (expected, expected, expected),
        ).fetchone()
        if not grants or any(int(value) != 0 for value in grants.values()):
            raise RuntimeError(f"bot_notification_identity_preflight_failed:{lane}:direct_relation_privilege")

    def _verified(self, dsn: str, lane: str):
        conn = self._connect(dsn)
        try:
            self._attest_connection(conn, lane)
            return conn
        except Exception:
            conn.close()
            raise

    def preflight(self):
        for dsn, lane in ((self.dsn, "background"), (self.delivery_dsn, "delivery"),
                          (self.transport_dsn, "transport")):
            with self._verified(dsn, lane):
                pass

    def _c(self):
        return self._verified(self.dsn, "background")

    def _lane(self, dsn: str, lane: str):
        return self._verified(dsn, lane)

    def _delivery_scalar(self, sql: str, args):
        with self._lane(self.delivery_dsn, "delivery") as conn:
            row = conn.execute(sql, args).fetchone()
            if row is None or "result" not in row:
                raise RuntimeError("bot_notification_delivery_result_missing")
            return row["result"]

    def queue_due_recalls(self, *, now: datetime | None = None, limit: int = 200) -> int:
        return int(self._scalar("SELECT public.bot_b59_queue_due_recalls(%s) AS result", (_limit(limit),)))

    def queue_due_montera(self, *, now: datetime | None = None, limit: int = 200) -> int:
        return int(self._scalar("SELECT public.bot_b59_queue_due_montera(%s) AS result", (_limit(limit),)))

    def queue_due_abandoned(self, *, now: datetime | None = None, limit: int = 200) -> int:
        return int(self._scalar("SELECT public.bot_b59_queue_due_abandoned(%s) AS result", (_limit(limit),)))

    def queue_due_payout_delays(self, *, warn_minutes: int, now: datetime | None = None, limit: int = 30) -> int:
        return int(self._scalar("SELECT public.bot_b59_queue_due_payout_delays(%s) AS result", (_limit(limit),)))

    def queue_due_winbacks(self, *, discount, valid_hours: int, now: datetime | None = None, limit: int = 20) -> int:
        return int(self._scalar("SELECT public.bot_b59_queue_due_winbacks(%s) AS result", (_limit(limit),)))

    def claim_notification(self, *, kind: str | None = None):
        if kind is not None and kind not in KINDS:
            raise ValueError("invalid_bot_notification_kind")
        with self._lane(self.delivery_dsn, "delivery") as conn:
            row = conn.execute(
                "SELECT id,kind,dedupe_key,payload,attempts,recipient_id,attempt_token "
                "FROM public.bot_b53_delivery_claim(%s)", (kind,),
            ).fetchone()
        item = _decode_job(row)
        if item is not None and item.get("attempt_token") is not None:
            item["attempt_token"] = str(item["attempt_token"])
        return item

    def pre_submit(self, ident: int, *, attempt_token: str, client_correlation_id: str) -> str:
        return str(self._delivery_scalar(
            "SELECT public.bot_b61_delivery_pre_submit(%s,%s::uuid,%s::uuid) AS result",
            (int(ident), attempt_token, client_correlation_id),
        ))

    def mark_local_manual(self, ident: int, *, attempt_token: str,
                          reason_code: str, evidence_sha256: str) -> bool:
        return bool(self._delivery_scalar(
            "SELECT public.bot_b61_delivery_mark_local_manual(%s,%s::uuid,%s,%s) AS result",
            (int(ident), attempt_token, reason_code, evidence_sha256),
        ))

    def record_delivery_evidence(self, ident: int, *, attempt_token: str, outcome: str,
                                 client_correlation_id: str,
                                 provider_request_id: str | None,
                                 provider_message_id: str | None,
                                 reason_code: str | None, response_sha256: str,
                                 observed_at: datetime):
        with self._lane(self.transport_dsn, "transport") as conn:
            row = conn.execute(
                "SELECT public.bot_b62_transport_record_evidence(%s,%s::uuid,%s::uuid,%s,%s,%s,%s,%s,%s) AS result",
                (int(ident), attempt_token, client_correlation_id, outcome, provider_request_id,
                 provider_message_id, reason_code, response_sha256, _utc(observed_at)),
            ).fetchone()
            if row is None:
                raise RuntimeError("bot_notification_transport_result_missing")
            return None if row["result"] is None else str(row["result"])

    def mark_notification_sent(self, ident: int, *, attempt_token: str, evidence_id: str) -> bool:
        result = str(self._delivery_scalar(
            "SELECT public.bot_b62_consume_accepted(%s,%s::uuid,%s::uuid) AS result",
            (int(ident), attempt_token, evidence_id),
        ))
        return result in {"SENT", "ALREADY_SENT"}

    def retry_notification_pre_submit(self, ident: int, *, attempt_token: str, evidence_id: str) -> str:
        return str(self._delivery_scalar(
            "SELECT public.bot_b53_delivery_retry_pre_submit(%s,%s::uuid,%s::uuid) AS result",
            (int(ident), attempt_token, evidence_id),
        ))

    def mark_notification_manual(self, ident: int, *, attempt_token: str, evidence_id: str) -> bool:
        return bool(self._delivery_scalar(
            "SELECT public.bot_b53_delivery_mark_manual(%s,%s::uuid,%s::uuid) AS result",
            (int(ident), attempt_token, evidence_id),
        ))

    def retry_notification(self, ident: int) -> bool:
        raise RuntimeError("id_only_notification_retry_disabled")


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if os.getenv("BOT_NOTIFICATION_B53_HARDENED_RUNTIME_ENABLED", "").lower() in {
        "1", "true", "yes"
    }:
        background = os.getenv("BOT_NOTIFICATION_BACKGROUND_DATABASE_URL", "").strip()
        delivery = os.getenv("BOT_NOTIFICATION_DELIVERY_DATABASE_URL", "").strip()
        transport = os.getenv("BOT_NOTIFICATION_TRANSPORT_DATABASE_URL", "").strip()
        if not background or not delivery or not transport:
            raise RuntimeError("bot_notification_hardened_database_urls_missing")
        if len({background, delivery, transport}) != 3:
            raise RuntimeError("bot_notification_hardened_database_urls_not_distinct")
        if os.getenv("BOT_NOTIFICATION_B5_ACL_ADAPTER_ENABLED", "").lower() in {"1", "true", "yes"}:
            raise RuntimeError("bot_notification_hardened_legacy_flag_conflict")
        if any(db_runtime.backend(item) != "postgresql" for item in (background, delivery, transport)):
            raise RuntimeError("bot_notification_hardened_postgresql_required")
        return PostgresB53HardenedBotNotificationStore(background, delivery, transport)
    if not url:
        return SQLiteBotNotificationStore(sqlite_path)
    if (
        db_runtime.backend(url) != "postgresql"
        or os.getenv("BOT_NOTIFICATION_POSTGRES_ENABLED", "").lower()
        not in {"1", "true", "yes"}
    ):
        raise RuntimeError("postgres_bot_notification_store_not_enabled")
    if os.getenv("BOT_NOTIFICATION_B5_ACL_ADAPTER_ENABLED", "").lower() in {
        "1", "true", "yes"
    }:
        return PostgresB5BotNotificationStore(url)
    return PostgresBotNotificationStore(url)
