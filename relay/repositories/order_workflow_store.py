"""Narrow compare-and-set mutations for the canonical buy-order workflow.

This module deliberately exposes business operations, never caller-supplied SQL or
arbitrary status transitions.  Authentication remains an adapter concern; methods
whose name ends in ``_for_owner`` additionally enforce ownership in the database.
"""
from __future__ import annotations

import os
from decimal import Decimal, InvalidOperation
from typing import Protocol

from core import db_runtime
from core.txid import normalize_txid


_REOPENABLE = ("cancelled", "expired", "failed")
_VERIFICATION_TYPES = ("video", "pdf-success")
RECEIPT_REJECTED_EVENT = "receipt_rejected"


class OrderWorkflowStore(Protocol):
    def cancel_pending_for_owner(self, order_id: int, user_id: int) -> bool: ...
    def reopen_review(self, order_id: int) -> bool: ...
    def reject_review(self, order_id: int) -> bool: ...
    def mark_sent(self, order_id: int, txid: str) -> dict: ...
    def request_verification(self, order_id: int, requested_type: str) -> dict: ...
    def clear_verification(self, order_id: int, requested_type: str) -> bool: ...
    def retry_amount_for_owner(self, order_id: int, user_id: int, amount) -> bool: ...
    def set_montera_invoice(self, order_id: int, invoice_id: str, receipt_deadline) -> bool: ...


def _amount(value) -> Decimal:
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError("invalid_order_amount") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError("invalid_order_amount")
    return amount


def _verification_type(value: str) -> str:
    value = str(value or "").strip()
    if value not in _VERIFICATION_TYPES:
        raise ValueError("invalid_verification_type")
    return value


def _invoice_id(value: str) -> str:
    value = str(value or "").strip()
    if not value or len(value) > 255:
        raise ValueError("invalid_montera_invoice_id")
    return value


class SQLiteOrderWorkflowStore:
    def __init__(self, path: str, *, timeout: float = 10):
        self.path, self.timeout = path, timeout

    def _c(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def cancel_pending_for_owner(self, order_id: int, user_id: int) -> bool:
        with self._c() as c:
            changed = c.execute(
                "UPDATE orders SET status='cancelled',updated_at=CURRENT_TIMESTAMP "
                "WHERE order_id=? AND user_id=? AND status='pending'",
                (int(order_id), int(user_id)),).rowcount
            c.commit()
            return changed == 1

    def reopen_review(self, order_id: int) -> bool:
        with self._c() as c:
            marks = ",".join("?" for _ in _REOPENABLE)
            changed = c.execute(
                f"UPDATE orders SET status='pending',updated_at=CURRENT_TIMESTAMP "
                f"WHERE order_id=? AND status IN({marks})",
                (int(order_id), *_REOPENABLE),).rowcount
            c.commit()
            return changed == 1

    def reject_review(self, order_id: int) -> bool:
        oid = int(order_id)
        with self._c() as c:
            c.execute("BEGIN IMMEDIATE")
            changed = c.execute(
                "UPDATE orders SET status='cancelled',updated_at=CURRENT_TIMESTAMP "
                "WHERE order_id=? AND status='pending'", (oid,)).rowcount
            if changed != 1:
                c.rollback()
                return False
            c.execute("INSERT OR IGNORE INTO sent_notifications(order_id,event) "
                      "VALUES(?,?)", (oid, RECEIPT_REJECTED_EVENT))
            c.commit()
            return True

    def mark_sent(self, order_id: int, txid: str) -> dict:
        oid = int(order_id)
        with self._c() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT currency,status,paid_btc_tx FROM orders WHERE order_id=?",
                            (oid,)).fetchone()
            if not row:
                c.rollback(); return {"action": "missing", "order_id": oid}
            canon = normalize_txid(txid, row[0])
            if not canon:
                c.rollback(); return {"action": "invalid_txid", "order_id": oid}
            if row[1] != "paid" or (row[2] or ""):
                c.rollback(); return {"action": "status_conflict", "order_id": oid,
                                      "status": row[1]}
            changed = c.execute(
                "UPDATE orders SET status='sent',paid_btc_tx=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE order_id=? AND status='paid' AND (paid_btc_tx IS NULL OR paid_btc_tx='')",
                (canon, oid)).rowcount
            if changed != 1:
                raise RuntimeError("order_sent_transition_lost")
            c.commit()
            return {"action": "transitioned", "order_id": oid, "txid": canon}

    def request_verification(self, order_id: int, requested_type: str) -> dict:
        oid, kind = int(order_id), _verification_type(requested_type)
        with self._c() as c:
            changed = c.execute(
                "UPDATE orders SET verification_requested=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE order_id=? AND status='pending' AND "
                "(verification_requested IS NULL OR verification_requested='')",
                (kind, oid)).rowcount
            row = c.execute("SELECT user_id,verification_requested,status FROM orders "
                            "WHERE order_id=?", (oid,)).fetchone()
            c.commit()
        if not row:
            return {"action": "missing", "order_id": oid}
        return {"action": "requested" if changed == 1 else "conflict", "order_id": oid,
                "user_id": row[0], "verification_requested": row[1], "status": row[2]}

    def clear_verification(self, order_id: int, requested_type: str) -> bool:
        kind = _verification_type(requested_type)
        with self._c() as c:
            changed = c.execute(
                "UPDATE orders SET verification_requested=NULL,updated_at=CURRENT_TIMESTAMP "
                "WHERE order_id=? AND verification_requested=?",
                (int(order_id), kind)).rowcount
            c.commit()
            return changed == 1

    def retry_amount_for_owner(self, order_id: int, user_id: int, amount) -> bool:
        amount = _amount(amount)
        with self._c() as c:
            changed = c.execute(
                "UPDATE orders SET rub_amount=?,updated_at=CURRENT_TIMESTAMP "
                "WHERE order_id=? AND user_id=? AND status='pending'",
                (str(amount), int(order_id), int(user_id))).rowcount
            c.commit()
            return changed == 1

    def set_montera_invoice(self, order_id: int, invoice_id: str, receipt_deadline) -> bool:
        invoice_id = _invoice_id(invoice_id)
        if receipt_deadline is None:
            raise ValueError("invalid_receipt_deadline")
        with self._c() as c:
            changed = c.execute(
                "UPDATE orders SET montera_invoice_id=?,receipt_deadline=?,"
                "updated_at=CURRENT_TIMESTAMP WHERE order_id=? AND status='pending' AND "
                "(montera_invoice_id IS NULL OR montera_invoice_id='' OR montera_invoice_id=?)",
                (invoice_id, receipt_deadline, int(order_id), invoice_id)).rowcount
            c.commit()
            return changed == 1


class PostgresOrderWorkflowStore(SQLiteOrderWorkflowStore):
    def __init__(self, dsn: str): self.dsn = dsn
    def _c(self):
        import psycopg
        return psycopg.connect(self.dsn)

    def cancel_pending_for_owner(self, order_id: int, user_id: int) -> bool:
        with self._c() as c:
            cur=c.execute("UPDATE orders SET status='cancelled',updated_at=now() WHERE "
                          "order_id=%s AND user_id=%s AND status='pending'",(int(order_id),int(user_id)))
            return cur.rowcount == 1

    def reopen_review(self, order_id: int) -> bool:
        with self._c() as c:
            cur=c.execute("UPDATE orders SET status='pending',updated_at=now() WHERE "
                          "order_id=%s AND status=ANY(%s)",(int(order_id),list(_REOPENABLE)))
            return cur.rowcount == 1

    def reject_review(self, order_id: int) -> bool:
        oid=int(order_id)
        with self._c() as c:
            cur=c.execute("UPDATE orders SET status='cancelled',updated_at=now() WHERE "
                          "order_id=%s AND status='pending'",(oid,))
            if cur.rowcount != 1: c.rollback(); return False
            c.execute("INSERT INTO sent_notifications(order_id,event) VALUES(%s,%s) "
                      "ON CONFLICT(order_id,event) DO NOTHING",
                      (oid, RECEIPT_REJECTED_EVENT))
            return True

    def mark_sent(self, order_id: int, txid: str) -> dict:
        oid=int(order_id)
        with self._c() as c:
            row=c.execute("SELECT currency,status,paid_btc_tx FROM orders WHERE order_id=%s FOR UPDATE",
                          (oid,)).fetchone()
            if not row: return {"action":"missing","order_id":oid}
            canon=normalize_txid(txid,row[0])
            if not canon: return {"action":"invalid_txid","order_id":oid}
            if row[1] != "paid" or (row[2] or ""):
                return {"action":"status_conflict","order_id":oid,"status":row[1]}
            cur=c.execute("UPDATE orders SET status='sent',paid_btc_tx=%s,updated_at=now() "
                          "WHERE order_id=%s AND status='paid' AND "
                          "(paid_btc_tx IS NULL OR paid_btc_tx='')",(canon,oid))
            if cur.rowcount != 1: raise RuntimeError("order_sent_transition_lost")
            return {"action":"transitioned","order_id":oid,"txid":canon}

    def request_verification(self, order_id: int, requested_type: str) -> dict:
        oid,kind=int(order_id),_verification_type(requested_type)
        with self._c() as c:
            row=c.execute("UPDATE orders SET verification_requested=%s,updated_at=now() WHERE "
                          "order_id=%s AND status='pending' AND "
                          "(verification_requested IS NULL OR verification_requested='') "
                          "RETURNING user_id,verification_requested,status",(kind,oid)).fetchone()
            if row: return {"action":"requested","order_id":oid,"user_id":row[0],
                            "verification_requested":row[1],"status":row[2]}
            row=c.execute("SELECT user_id,verification_requested,status FROM orders WHERE order_id=%s",
                          (oid,)).fetchone()
            if not row: return {"action":"missing","order_id":oid}
            return {"action":"conflict","order_id":oid,"user_id":row[0],
                    "verification_requested":row[1],"status":row[2]}

    def clear_verification(self, order_id: int, requested_type: str) -> bool:
        kind=_verification_type(requested_type)
        with self._c() as c:
            cur=c.execute("UPDATE orders SET verification_requested=NULL,updated_at=now() WHERE "
                          "order_id=%s AND verification_requested=%s",(int(order_id),kind))
            return cur.rowcount == 1

    def retry_amount_for_owner(self, order_id: int, user_id: int, amount) -> bool:
        amount=_amount(amount)
        with self._c() as c:
            cur=c.execute("UPDATE orders SET rub_amount=%s,updated_at=now() WHERE "
                          "order_id=%s AND user_id=%s AND status='pending'",
                          (amount,int(order_id),int(user_id)))
            return cur.rowcount == 1

    def set_montera_invoice(self, order_id: int, invoice_id: str, receipt_deadline) -> bool:
        invoice_id=_invoice_id(invoice_id)
        if receipt_deadline is None: raise ValueError("invalid_receipt_deadline")
        with self._c() as c:
            cur=c.execute("UPDATE orders SET montera_invoice_id=%s,receipt_deadline=%s,updated_at=now() "
                          "WHERE order_id=%s AND status='pending' AND (montera_invoice_id IS NULL OR "
                          "montera_invoice_id='' OR montera_invoice_id=%s)",
                          (invoice_id,receipt_deadline,int(order_id),invoice_id))
            return cur.rowcount == 1


def from_environment(*, sqlite_path: str) -> OrderWorkflowStore:
    url=os.getenv("DATABASE_URL","").strip()
    if not url: return SQLiteOrderWorkflowStore(sqlite_path)
    if (db_runtime.backend(url) != "postgresql" or
            os.getenv("ORDER_WORKFLOW_POSTGRES_ENABLED","").strip().lower()
            not in {"1","true","yes"}):
        raise RuntimeError("postgres_order_workflow_store_not_enabled")
    return PostgresOrderWorkflowStore(url)
