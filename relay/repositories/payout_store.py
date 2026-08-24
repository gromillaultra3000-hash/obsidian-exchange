"""Payout worker persistence contract for SQLite and PostgreSQL."""
from __future__ import annotations

import os
import sqlite3
from typing import Any, Callable, Protocol

from core import db_runtime


class SQLiteOrderIntentQueries:
    """SQLite order-intent implementation shared with the compatibility facade."""

    @staticmethod
    def ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute("SELECT id FROM payout_intents WHERE 0")
        conn.execute("SELECT id FROM payout_intent_audit WHERE 0")

    @staticmethod
    def row(conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
        old_factory = conn.row_factory
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM payout_intents WHERE order_id=?", (int(order_id),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.row_factory = old_factory

    @classmethod
    def create(cls, conn: sqlite3.Connection, *, order_id: int, rub_amount: float,
               crypto_amount: float, currency: str, network: str | None,
               destination: str, source: str,
               requested_by: str | int | None = None) -> dict[str, Any]:
        cls.ensure_schema(conn)
        oid = int(order_id)
        payload = {
            "rub_amount": float(rub_amount),
            "crypto_amount": float(crypto_amount),
            "currency": str(currency).upper(),
            "network": str(network).upper() if network else None,
            "destination": str(destination),
            "source": str(source),
            "requested_by": str(requested_by) if requested_by is not None else None,
        }
        conn.execute(
            "INSERT OR IGNORE INTO payout_intents(order_id,idempotency_key,source,"
            "requested_by,rub_amount,crypto_amount,currency,network,destination) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (oid, f"payout_{oid}", payload["source"], payload["requested_by"],
             payload["rub_amount"], payload["crypto_amount"], payload["currency"],
             payload["network"], payload["destination"]),
        )
        current = cls.row(conn, oid)
        if current is None:
            raise RuntimeError("payout_intent_create_failed")
        if not (
            abs(float(current["rub_amount"]) - payload["rub_amount"]) <= 1e-12
            and abs(float(current["crypto_amount"]) - payload["crypto_amount"]) <= 1e-12
            and current["currency"] == payload["currency"]
            and current["network"] == payload["network"]
            and current["destination"] == payload["destination"]
        ):
            raise ValueError("payout_intent_payload_mismatch")
        return current

    @classmethod
    def claim(cls, conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
        cur = conn.execute(
            "UPDATE payout_intents SET state='processing',attempts=attempts+1,"
            "claimed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE order_id=? AND state='pending'", (int(order_id),))
        return cls.row(conn, order_id) if cur.rowcount == 1 else None

    @classmethod
    def claim_next(cls, conn: sqlite3.Connection) -> dict[str, Any] | None:
        cls.ensure_schema(conn)
        row = conn.execute("SELECT order_id FROM payout_intents WHERE state='pending' "
                           "ORDER BY id LIMIT 1").fetchone()
        return cls.claim(conn, int(row[0])) if row else None

    @staticmethod
    def succeed(conn: sqlite3.Connection, order_id: int, txid: str) -> bool:
        tx = str(txid or "").strip()
        if not tx:
            raise ValueError("payout_intent_txid_required")
        cur = conn.execute(
            "UPDATE payout_intents SET state='succeeded',txid=?,error_code=NULL,"
            "finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE order_id=? AND state='processing'", (tx, int(order_id)))
        return cur.rowcount == 1

    @staticmethod
    def review(conn: sqlite3.Connection, order_id: int, error_code: str) -> bool:
        code = str(error_code or "signer_error")[:80]
        cur = conn.execute(
            "UPDATE payout_intents SET state='review',error_code=?,"
            "finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE order_id=? AND state='processing'", (code, int(order_id)))
        return cur.rowcount == 1

    @classmethod
    def get(cls, conn: sqlite3.Connection, order_id: int) -> dict[str, Any] | None:
        cls.ensure_schema(conn)
        return cls.row(conn, order_id)

    @classmethod
    def admin_confirm_txid(cls, conn: sqlite3.Connection, order_id: int, txid: str,
                           *, actor: str | int, evidence: str) -> bool:
        tx, proof = str(txid or "").strip(), str(evidence or "").strip()[:500]
        if not tx or not proof:
            raise ValueError("chain_evidence_required")
        oid = int(order_id)
        row = cls.row(conn, oid)
        if not row or row["state"] not in ("processing", "review"):
            return False
        cur = conn.execute(
            "UPDATE payout_intents SET state='succeeded',txid=?,error_code=NULL,"
            "finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE order_id=? AND state=?", (tx, oid, row["state"]))
        if cur.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO payout_intent_audit(order_id,actor,action,from_state,"
            "to_state,evidence,txid) VALUES (?,?,?,?,?,?,?)",
            (oid, str(actor), "confirm_txid", row["state"], "succeeded", proof, tx))
        return True

    @staticmethod
    def admin_requeue_absent(conn: sqlite3.Connection, order_id: int, *,
                             actor: str | int, evidence: str) -> bool:
        proof = str(evidence or "").strip()[:500]
        if not proof:
            raise ValueError("absence_evidence_required")
        oid = int(order_id)
        cur = conn.execute(
            "UPDATE payout_intents SET state='pending',error_code=NULL,txid=NULL,"
            "claimed_at=NULL,finished_at=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE order_id=? AND state='review'", (oid,))
        if cur.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO payout_intent_audit(order_id,actor,action,from_state,"
            "to_state,evidence) VALUES (?,?,?,?,?,?)",
            (oid, str(actor), "requeue_after_absence", "review", "pending", proof))
        return True


class SQLiteReferralIntentQueries:
    """All SQLite referral-intent persistence; core exposes only a facade."""

    @staticmethod
    def ensure_schema(conn: sqlite3.Connection) -> None:
        conn.execute("SELECT id FROM referral_payout_intents WHERE 0")
        conn.execute("SELECT id FROM referral_payout_intent_audit WHERE 0")

    @staticmethod
    def row(conn: sqlite3.Connection, intent_id: int) -> dict[str, Any] | None:
        old_factory = conn.row_factory
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT * FROM referral_payout_intents WHERE id=?", (int(intent_id),)
            ).fetchone()
            return dict(row) if row else None
        finally:
            conn.row_factory = old_factory

    @classmethod
    def create(cls, conn: sqlite3.Connection, *, user_id: int, destination: str,
               minimum_btc: float) -> dict[str, Any]:
        cls.ensure_schema(conn)
        uid = int(user_id)
        old_factory = conn.row_factory
        conn.row_factory = sqlite3.Row
        try:
            active = conn.execute(
                "SELECT * FROM referral_payout_intents WHERE user_id=? AND state IN "
                "('pending','processing','succeeded','review')", (uid,),
            ).fetchone()
            if active:
                return dict(active)
        finally:
            conn.row_factory = old_factory
        total = float(conn.execute(
            "SELECT COALESCE(SUM(total_bonus_btc),0) FROM referrals WHERE referrer_id=?",
            (uid,),
        ).fetchone()[0] or 0)
        if total + 1e-12 < float(minimum_btc):
            raise ValueError("referral_balance_below_minimum")
        seq = int(conn.execute(
            "SELECT COALESCE(MAX(id),0)+1 FROM referral_payout_intents"
        ).fetchone()[0])
        conn.execute(
            "INSERT INTO referral_payout_intents(user_id,idempotency_key,crypto_amount,"
            "currency,destination) VALUES(?,?,?,?,?)",
            (uid, f"referral_{uid}_{seq}", total, "BTC", str(destination)),
        )
        item = cls.row(conn, int(conn.execute("SELECT last_insert_rowid()").fetchone()[0]))
        if item is None:
            raise RuntimeError("referral_payout_intent_create_failed")
        return item

    @classmethod
    def get(cls, conn: sqlite3.Connection, intent_id: int) -> dict[str, Any] | None:
        cls.ensure_schema(conn)
        return cls.row(conn, intent_id)

    @classmethod
    def claim_next(cls, conn: sqlite3.Connection) -> dict[str, Any] | None:
        cls.ensure_schema(conn)
        row = conn.execute(
            "SELECT id FROM referral_payout_intents WHERE state='pending' ORDER BY id LIMIT 1"
        ).fetchone()
        if not row:
            return None
        ident = int(row[0])
        changed = conn.execute(
            "UPDATE referral_payout_intents SET state='processing',attempts=attempts+1,"
            "claimed_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND state='pending'", (ident,),
        )
        if changed.rowcount != 1:
            return None
        result = cls.row(conn, ident)
        if result:
            result.update(source="referral", rub_amount=0.0, order_id=None,
                          intent_type="referral")
        return result

    @staticmethod
    def succeed(conn: sqlite3.Connection, intent_id: int, txid: str) -> bool:
        tx = str(txid or "").strip()
        if not tx:
            raise ValueError("payout_intent_txid_required")
        return conn.execute(
            "UPDATE referral_payout_intents SET state='succeeded',txid=?,error_code=NULL,"
            "finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND state='processing'", (tx, int(intent_id)),
        ).rowcount == 1

    @staticmethod
    def review(conn: sqlite3.Connection, intent_id: int, error_code: str) -> bool:
        return conn.execute(
            "UPDATE referral_payout_intents SET state='review',error_code=?,"
            "finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND state='processing'",
            (str(error_code)[:80], int(intent_id)),
        ).rowcount == 1

    @classmethod
    def admin_confirm_txid(cls, conn: sqlite3.Connection, intent_id: int, txid: str,
                           *, actor: str | int, evidence: str) -> bool:
        tx, proof = str(txid or "").strip(), str(evidence or "").strip()[:500]
        if not tx or not proof:
            raise ValueError("chain_evidence_required")
        ident = int(intent_id)
        row = cls.row(conn, ident)
        if not row or row["state"] not in ("processing", "review"):
            return False
        changed = conn.execute(
            "UPDATE referral_payout_intents SET state='succeeded',txid=?,error_code=NULL,"
            "finished_at=CURRENT_TIMESTAMP,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND state=?", (tx, ident, row["state"]),
        )
        if changed.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO referral_payout_intent_audit(intent_id,actor,action,from_state,"
            "to_state,evidence,txid) VALUES(?,?,?,?,?,?,?)",
            (ident, str(actor), "confirm_txid", row["state"], "succeeded", proof, tx),
        )
        return True

    @staticmethod
    def admin_requeue_absent(conn: sqlite3.Connection, intent_id: int, *,
                             actor: str | int, evidence: str) -> bool:
        proof = str(evidence or "").strip()[:500]
        if not proof:
            raise ValueError("absence_evidence_required")
        ident = int(intent_id)
        changed = conn.execute(
            "UPDATE referral_payout_intents SET state='pending',error_code=NULL,txid=NULL,"
            "claimed_at=NULL,finished_at=NULL,updated_at=CURRENT_TIMESTAMP "
            "WHERE id=? AND state='review'", (ident,),
        )
        if changed.rowcount != 1:
            return False
        conn.execute(
            "INSERT INTO referral_payout_intent_audit(intent_id,actor,action,from_state,"
            "to_state,evidence) VALUES(?,?,?,?,?,?)",
            (ident, str(actor), "requeue_after_absence", "review", "pending", proof),
        )
        return True

class PayoutStore(Protocol):
    def create_order(self, *, order_id: int, rub_amount: float,
                     crypto_amount: float, currency: str, network: str | None,
                     destination: str, source: str,
                     requested_by: str | int | None = None) -> dict[str, Any]: ...
    def order(self, order_id: int) -> dict[str, Any] | None: ...
    def order_exists(self, order_id: int) -> bool: ...
    def review_items(self, limit: int = 30) -> list[dict[str, Any]]: ...
    def confirm_order_txid(self, order_id: int, txid: str, *, actor: str | int,
                           evidence: str) -> bool: ...
    def requeue_order_absent(self, order_id: int, *, actor: str | int,
                             evidence: str) -> bool: ...
    def request_referral(self, *, user_id: int, destination: str,
                         minimum_btc: float) -> dict[str, Any]: ...
    def referral(self, intent_id: int) -> dict[str, Any] | None: ...
    def referral_review_items(self, limit: int = 30) -> list[dict[str, Any]]: ...
    def confirm_referral_txid(self, intent_id: int, txid: str, *, actor: str | int,
                              evidence: str) -> bool: ...
    def requeue_referral_absent(self, intent_id: int, *, actor: str | int,
                                evidence: str) -> bool: ...
    def claim_next(self) -> dict[str, Any] | None: ...
    def succeed(self, intent: dict[str, Any], txid: str) -> bool: ...
    def review(self, intent: dict[str, Any], error_code: str) -> bool: ...


def _identity(intent: dict[str, Any]) -> tuple[str, int]:
    kind = "referral" if intent.get("intent_type") == "referral" else "order"
    ident = int(intent["id"] if kind == "referral" else intent["order_id"])
    return kind, ident


class SQLitePayoutStore:
    def __init__(self, path: str, *, timeout: float = 10):
        self.path, self.timeout = path, timeout

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def create_order(self, *, order_id: int, rub_amount: float,
                     crypto_amount: float, currency: str, network: str | None,
                     destination: str, source: str,
                     requested_by: str | int | None = None) -> dict[str, Any]:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            intent = SQLiteOrderIntentQueries.create(
                conn, order_id=order_id, rub_amount=rub_amount,
                crypto_amount=crypto_amount, currency=currency, network=network,
                destination=destination, source=source, requested_by=requested_by,
            )
            conn.commit()
            return intent

    def order(self, order_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            return SQLiteOrderIntentQueries.get(conn, int(order_id))

    def order_exists(self, order_id: int) -> bool:
        with self._connect() as conn:
            SQLiteOrderIntentQueries.ensure_schema(conn)
            return conn.execute(
                "SELECT 1 FROM payout_intents WHERE order_id=?", (int(order_id),)
            ).fetchone() is not None

    def review_items(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            SQLiteOrderIntentQueries.ensure_schema(conn)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT p.order_id,p.state,p.currency,p.network,p.crypto_amount,"
                "p.destination,p.txid,p.error_code,p.claimed_at,p.updated_at,o.status "
                "AS order_status FROM payout_intents p JOIN orders o "
                "ON o.order_id=p.order_id WHERE p.state IN ('processing','review') "
                "ORDER BY p.updated_at,p.id LIMIT ?", (max(1, min(int(limit), 100)),)
            ).fetchall()
            return [dict(row) for row in rows]

    def confirm_order_txid(self, order_id: int, txid: str, *, actor: str | int,
                           evidence: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ok = SQLiteOrderIntentQueries.admin_confirm_txid(
                conn, order_id, txid, actor=actor, evidence=evidence)
            conn.commit()
            return ok

    def requeue_order_absent(self, order_id: int, *, actor: str | int,
                             evidence: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ok = SQLiteOrderIntentQueries.admin_requeue_absent(
                conn, order_id, actor=actor, evidence=evidence)
            conn.commit()
            return ok

    def request_referral(self, *, user_id: int, destination: str,
                         minimum_btc: float) -> dict[str, Any]:
        uid = int(user_id)
        target = str(destination or "").strip()
        minimum = float(minimum_btc)
        if not target:
            raise ValueError("referral_destination_required")
        if minimum <= 0:
            raise ValueError("referral_minimum_invalid")
        with self._connect() as conn:
            SQLiteReferralIntentQueries.ensure_schema(conn)
            conn.execute("BEGIN IMMEDIATE")
            item = SQLiteReferralIntentQueries.create(
                conn, user_id=uid, destination=target, minimum_btc=minimum)
            conn.commit()
            return item

    def referral(self, intent_id: int) -> dict[str, Any] | None:
        with self._connect() as conn:
            return SQLiteReferralIntentQueries.get(conn, int(intent_id))

    def referral_review_items(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn:
            SQLiteReferralIntentQueries.ensure_schema(conn)
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id,user_id,state,currency,network,crypto_amount,destination,"
                "txid,error_code,claimed_at,updated_at FROM referral_payout_intents "
                "WHERE state IN ('processing','review') ORDER BY updated_at,id LIMIT ?",
                (max(1, min(int(limit), 100)),),
            ).fetchall()
            return [dict(row) for row in rows]

    def confirm_referral_txid(self, intent_id: int, txid: str, *, actor: str | int,
                              evidence: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ok = SQLiteReferralIntentQueries.admin_confirm_txid(
                conn, intent_id, txid, actor=actor, evidence=evidence)
            conn.commit()
            return ok

    def requeue_referral_absent(self, intent_id: int, *, actor: str | int,
                                evidence: str) -> bool:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            ok = SQLiteReferralIntentQueries.admin_requeue_absent(
                conn, intent_id, actor=actor, evidence=evidence)
            conn.commit()
            return ok

    def claim_next(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            intent = SQLiteOrderIntentQueries.claim_next(conn)
            if intent is None:
                intent = SQLiteReferralIntentQueries.claim_next(conn)
            conn.commit()
            return intent

    def succeed(self, intent: dict[str, Any], txid: str) -> bool:
        kind, ident = _identity(intent)
        with self._connect() as conn:
            ok = (SQLiteReferralIntentQueries.succeed(conn, ident, txid)
                  if kind == "referral" else SQLiteOrderIntentQueries.succeed(conn, ident, txid))
            conn.commit()
            return ok

    def review(self, intent: dict[str, Any], error_code: str) -> bool:
        kind, ident = _identity(intent)
        with self._connect() as conn:
            ok = (SQLiteReferralIntentQueries.review(conn, ident, error_code)
                  if kind == "referral" else SQLiteOrderIntentQueries.review(conn, ident, error_code))
            conn.commit()
            return ok


class PostgresPayoutStore:
    """DB-API store; connection factory is injectable for tests."""
    def __init__(self, dsn: str, connect: Callable[..., Any] | None = None):
        self.dsn, self._connector = dsn, connect

    def _connect(self):
        if self._connector is None:
            import psycopg
            from psycopg.rows import dict_row
            return psycopg.connect(self.dsn, row_factory=dict_row)
        return self._connector(self.dsn)

    @staticmethod
    def _intent(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        item = dict(row)
        for key in ("rub_amount", "crypto_amount"):
            if item.get(key) is not None:
                item[key] = float(item[key])
        return item

    def create_order(self, *, order_id: int, rub_amount: float,
                     crypto_amount: float, currency: str, network: str | None,
                     destination: str, source: str,
                     requested_by: str | int | None = None) -> dict[str, Any]:
        oid = int(order_id)
        payload = {
            "rub_amount": float(rub_amount),
            "crypto_amount": float(crypto_amount),
            "currency": str(currency).upper(),
            "network": str(network).upper() if network else None,
            "destination": str(destination),
            "source": str(source),
            "requested_by": str(requested_by) if requested_by is not None else None,
        }
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "INSERT INTO payout_intents(order_id,idempotency_key,source,requested_by,"
                "rub_amount,crypto_amount,currency,network,destination) "
                "VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT DO NOTHING",
                (oid, f"payout_{oid}", payload["source"], payload["requested_by"],
                 payload["rub_amount"], payload["crypto_amount"], payload["currency"],
                 payload["network"], payload["destination"]),
            )
            cur.execute("SELECT * FROM payout_intents WHERE order_id=%s FOR UPDATE", (oid,))
            current = self._intent(cur.fetchone())
            if current is None:
                raise RuntimeError("payout_intent_create_failed")
            immutable_match = (
                abs(current["rub_amount"] - payload["rub_amount"]) <= 1e-12
                and abs(current["crypto_amount"] - payload["crypto_amount"]) <= 1e-12
                and current["currency"] == payload["currency"]
                and current["network"] == payload["network"]
                and current["destination"] == payload["destination"]
            )
            if not immutable_match:
                raise ValueError("payout_intent_payload_mismatch")
            conn.commit()
            return current

    def order(self, order_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM payout_intents WHERE order_id=%s", (int(order_id),))
            return self._intent(cur.fetchone())

    def order_exists(self, order_id: int) -> bool:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT 1 FROM payout_intents WHERE order_id=%s", (int(order_id),))
            return cur.fetchone() is not None

    def review_items(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT p.order_id,p.state,p.currency,p.network,p.crypto_amount,"
                "p.destination,p.txid,p.error_code,p.claimed_at,p.updated_at,o.status "
                "AS order_status FROM payout_intents p JOIN orders o "
                "ON o.order_id=p.order_id WHERE p.state IN ('processing','review') "
                "ORDER BY p.updated_at,p.id LIMIT %s", (max(1, min(int(limit), 100)),),
            )
            return [self._intent(row) for row in cur.fetchall()]

    def confirm_order_txid(self, order_id: int, txid: str, *, actor: str | int,
                           evidence: str) -> bool:
        tx, proof = str(txid or "").strip(), str(evidence or "").strip()[:500]
        if not tx or not proof:
            raise ValueError("chain_evidence_required")
        oid = int(order_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT state FROM payout_intents WHERE order_id=%s FOR UPDATE", (oid,))
            row = cur.fetchone()
            if not row or row["state"] not in ("processing", "review"):
                return False
            previous = row["state"]
            cur.execute(
                "UPDATE payout_intents SET state='succeeded',txid=%s,error_code=NULL,"
                "finished_at=now(),updated_at=now() WHERE order_id=%s AND state=%s",
                (tx, oid, previous),
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                "INSERT INTO payout_intent_audit(order_id,actor,action,from_state,"
                "to_state,evidence,txid) VALUES(%s,%s,'confirm_txid',%s,'succeeded',%s,%s)",
                (oid, str(actor), previous, proof, tx),
            )
            conn.commit()
            return True

    def requeue_order_absent(self, order_id: int, *, actor: str | int,
                             evidence: str) -> bool:
        proof = str(evidence or "").strip()[:500]
        if not proof:
            raise ValueError("absence_evidence_required")
        oid = int(order_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE payout_intents SET state='pending',error_code=NULL,txid=NULL,"
                "claimed_at=NULL,finished_at=NULL,updated_at=now() "
                "WHERE order_id=%s AND state='review'", (oid,),
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                "INSERT INTO payout_intent_audit(order_id,actor,action,from_state,"
                "to_state,evidence) VALUES(%s,%s,'requeue_after_absence','review',"
                "'pending',%s)", (oid, str(actor), proof),
            )
            conn.commit()
            return True

    def request_referral(self, *, user_id: int, destination: str,
                         minimum_btc: float) -> dict[str, Any]:
        uid = int(user_id)
        target = str(destination or "").strip()
        minimum = float(minimum_btc)
        if not target:
            raise ValueError("referral_destination_required")
        if minimum <= 0:
            raise ValueError("referral_minimum_invalid")
        with self._connect() as conn, conn.cursor() as cur:
            # There may be neither an intent nor referral rows to lock. A
            # transaction-scoped per-user lock closes that first-request race.
            cur.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))",
                (f"referral_payout:{uid}",),
            )
            cur.execute(
                "SELECT * FROM referral_payout_intents WHERE user_id=%s "
                "AND state IN ('pending','processing','succeeded','review') FOR UPDATE",
                (uid,),
            )
            active = self._intent(cur.fetchone())
            if active is not None:
                conn.commit()
                return active
            cur.execute(
                "SELECT total_bonus_btc FROM referrals WHERE referrer_id=%s "
                "ORDER BY referred_id FOR UPDATE", (uid,),
            )
            total = sum(float(row["total_bonus_btc"] or 0) for row in cur.fetchall())
            if total + 1e-12 < minimum:
                raise ValueError("referral_balance_below_minimum")
            cur.execute(
                "SELECT nextval(pg_get_serial_sequence('referral_payout_intents','id')) AS id"
            )
            ident = int(cur.fetchone()["id"])
            cur.execute(
                "INSERT INTO referral_payout_intents(id,user_id,idempotency_key,"
                "crypto_amount,currency,destination) VALUES(%s,%s,%s,%s,'BTC',%s) "
                "RETURNING *",
                (ident, uid, f"referral_{uid}_{ident}", total, target),
            )
            item = self._intent(cur.fetchone())
            if item is None:
                raise RuntimeError("referral_payout_intent_create_failed")
            conn.commit()
            return item

    def referral(self, intent_id: int) -> dict[str, Any] | None:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute("SELECT * FROM referral_payout_intents WHERE id=%s",
                        (int(intent_id),))
            return self._intent(cur.fetchone())

    def referral_review_items(self, limit: int = 30) -> list[dict[str, Any]]:
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT id,user_id,state,currency,network,crypto_amount,destination,"
                "txid,error_code,claimed_at,updated_at FROM referral_payout_intents "
                "WHERE state IN ('processing','review') ORDER BY updated_at,id LIMIT %s",
                (max(1, min(int(limit), 100)),),
            )
            return [self._intent(row) for row in cur.fetchall()]

    def confirm_referral_txid(self, intent_id: int, txid: str, *, actor: str | int,
                              evidence: str) -> bool:
        tx, proof = str(txid or "").strip(), str(evidence or "").strip()[:500]
        if not tx or not proof:
            raise ValueError("chain_evidence_required")
        ident = int(intent_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT state FROM referral_payout_intents WHERE id=%s FOR UPDATE",
                (ident,),
            )
            row = cur.fetchone()
            if not row or row["state"] not in ("processing", "review"):
                return False
            previous = row["state"]
            cur.execute(
                "UPDATE referral_payout_intents SET state='succeeded',txid=%s,"
                "error_code=NULL,finished_at=now(),updated_at=now() "
                "WHERE id=%s AND state=%s", (tx, ident, previous),
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                "INSERT INTO referral_payout_intent_audit(intent_id,actor,action,"
                "from_state,to_state,evidence,txid) VALUES(%s,%s,'confirm_txid',%s,"
                "'succeeded',%s,%s)",
                (ident, str(actor), previous, proof, tx),
            )
            conn.commit()
            return True

    def requeue_referral_absent(self, intent_id: int, *, actor: str | int,
                                evidence: str) -> bool:
        proof = str(evidence or "").strip()[:500]
        if not proof:
            raise ValueError("absence_evidence_required")
        ident = int(intent_id)
        with self._connect() as conn, conn.cursor() as cur:
            cur.execute(
                "UPDATE referral_payout_intents SET state='pending',error_code=NULL,"
                "txid=NULL,claimed_at=NULL,finished_at=NULL,updated_at=now() "
                "WHERE id=%s AND state='review'", (ident,),
            )
            if cur.rowcount != 1:
                return False
            cur.execute(
                "INSERT INTO referral_payout_intent_audit(intent_id,actor,action,"
                "from_state,to_state,evidence) VALUES(%s,%s,'requeue_after_absence',"
                "'review','pending',%s)", (ident, str(actor), proof),
            )
            conn.commit()
            return True

    def claim_next(self) -> dict[str, Any] | None:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT * FROM claim_next_order_payout()")
                row = cur.fetchone()
                if row is None:
                    cur.execute("SELECT * FROM claim_next_referral_payout()")
                    row = cur.fetchone()
                    if row is not None:
                        row = dict(row); row.update(intent_type="referral", order_id=None,
                                                    source="referral", rub_amount=0.0)
                elif row is not None:
                    row = dict(row); row["intent_type"] = "order"
            conn.commit()
            return row

    def _finish(self, intent: dict[str, Any], *, state: str,
                txid: str | None = None, error_code: str | None = None) -> bool:
        kind, ident = _identity(intent)
        table = "referral_payout_intents" if kind == "referral" else "payout_intents"
        key = "id" if kind == "referral" else "order_id"
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    f"UPDATE {table} SET state=%s,txid=%s,error_code=%s,"
                    "finished_at=now(),updated_at=now() WHERE " + key + "=%s AND state='processing'",
                    (state, txid, error_code, ident))
                ok = cur.rowcount == 1
            conn.commit()
            return ok

    def succeed(self, intent: dict[str, Any], txid: str) -> bool:
        value = str(txid or "").strip()
        if not value:
            raise ValueError("payout_intent_txid_required")
        return self._finish(intent, state="succeeded", txid=value)

    def review(self, intent: dict[str, Any], error_code: str) -> bool:
        return self._finish(intent, state="review", error_code=str(error_code)[:80])


def from_environment(*, sqlite_path: str) -> PayoutStore:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLitePayoutStore(sqlite_path)
    if db_runtime.backend(url) != "postgresql":
        raise RuntimeError("unsupported_payout_database")
    if os.getenv("PAYOUT_POSTGRES_ENABLED", "").strip().lower() not in {"1", "true", "yes"}:
        raise RuntimeError("payout_postgres_not_enabled")
    return PostgresPayoutStore(url)
