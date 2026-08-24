"""Atomic E4 reservation plus canonical buy/sell order creation."""

from __future__ import annotations

import hashlib
import json
import os
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from core import db_runtime
from core.e4_action_reservation import (
    build_action_reservation_request, validate_action_reservation_request,
)


def _decimal(value: Any, field: str) -> Decimal:
    try:
        number = Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise ValueError(f"{field} is invalid") from exc
    if not number.is_finite() or number <= 0:
        raise ValueError(f"{field} is invalid")
    return number


def _text(value: Any, field: str, *, allow_empty: bool = False,
          maximum: int = 255) -> str:
    if not isinstance(value, str) or len(value) > maximum \
            or (not allow_empty and not value.strip()):
        raise ValueError(f"{field} is invalid")
    return value.strip()


def _fingerprint(value: Any) -> str:
    raw = (value.encode() if isinstance(value, str) else
           json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode())
    return hashlib.sha256(raw).hexdigest()


def _validate_common(reservation: dict[str, Any], draft: dict[str, Any],
                     assessment: dict[str, Any]) -> dict[str, Any]:
    value = validate_action_reservation_request(reservation)
    rebuilt = build_action_reservation_request(
        draft=draft, assessment=assessment,
        requested_at_epoch_ms=value["requestedAtEpochMs"],
        expires_at_epoch_ms=value["expiresAtEpochMs"])
    if rebuilt != value:
        raise ValueError("reservation does not bind exact draft and assessment")
    return value


def _validate_buy(value, draft, order):
    required = {"user_id", "username", "currency", "rub_amount", "destination",
                "network", "agreed_rate", "agreed_crypto_amount", "web_user_id"}
    if not isinstance(order, dict) or set(order) != required \
            or value["workflowMapping"] != "BUY_ORDER_CREATION" \
            or draft.get("side") != "BUY_CRYPTO" \
            or int(order["user_id"]) != value["actorUserId"]:
        raise ValueError("buy handoff schema or actor is invalid")
    destination = _text(order["destination"], "destination", maximum=512)
    if _fingerprint(destination) != draft["destination"]["destinationFingerprintSha256"]:
        raise ValueError("buy destination fingerprint differs")
    if (str(order["currency"]) != draft["amounts"]["receiveAsset"]
            or _decimal(order["rub_amount"], "rub_amount") != Decimal(
                draft["amounts"]["spendAmount"])
            or _decimal(order["agreed_crypto_amount"], "agreed_crypto_amount") != Decimal(
                draft["amounts"]["receiveAmount"])):
        raise ValueError("buy amounts differ from preview")
    _decimal(order["agreed_rate"], "agreed_rate")
    return {**order, "destination": destination,
            "username": _text(order["username"], "username", allow_empty=True),
            "currency": _text(order["currency"], "currency", maximum=16),
            "network": (_text(order["network"], "network", maximum=32)
                        if order["network"] is not None else None)}


def _validate_sell(value, draft, order):
    required = {"user_id", "currency", "crypto_amount", "rub_amount", "sbp_phone",
                "receive_address", "payout_method", "payout_bank", "payout_details",
                "payout_name"}
    if not isinstance(order, dict) or set(order) != required \
            or value["workflowMapping"] != "SELL_ORDER_CREATION" \
            or draft.get("side") != "SELL_CRYPTO" \
            or int(order["user_id"]) != value["actorUserId"]:
        raise ValueError("sell handoff schema or actor is invalid")
    payout = {field: _text(order[field], field, allow_empty=True) for field in (
        "sbp_phone", "payout_method", "payout_bank", "payout_details", "payout_name")}
    if _fingerprint(payout) != draft["destination"]["destinationFingerprintSha256"]:
        raise ValueError("sell destination fingerprint differs")
    if (str(order["currency"]) != draft["amounts"]["spendAsset"]
            or _decimal(order["crypto_amount"], "crypto_amount") != Decimal(
                draft["amounts"]["spendAmount"])
            or _decimal(order["rub_amount"], "rub_amount") != Decimal(
                draft["amounts"]["receiveAmount"])):
        raise ValueError("sell amounts differ from preview")
    return {**order, **payout,
            "currency": _text(order["currency"], "currency", maximum=16),
            "receive_address": _text(
                order["receive_address"], "receive_address", maximum=512)}


class SQLiteE4ActionHandoffStore:
    def __init__(self, path: str, *, timeout: float = 10,
                 fault_after_order: Callable[[], None] | None = None,
                 fault_before_commit: Callable[[], None] | None = None):
        self.path, self.timeout = path, timeout
        self.fault_after_order, self.fault_before_commit = (
            fault_after_order, fault_before_commit)
    def _c(self): return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def handoff(self, *, reservation, draft, assessment, order):
        value = _validate_common(reservation, draft, assessment)
        payload = (_validate_buy(value, draft, order)
                   if value["workflowMapping"] == "BUY_ORDER_CREATION"
                   else _validate_sell(value, draft, order))
        with self._c() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT request_id,payload_sha256,state,result_kind,result_id FROM "
                "e4_action_reservations WHERE draft_id=? OR "
                "(principal_ref=? AND idempotency_key_sha256=?) LIMIT 1",
                (value["draftId"], value["principalRef"],
                 value["idempotencyKeySha256"])).fetchone()
            if existing:
                if existing[0] == value["requestId"] and existing[1] == value["payloadSha256"] \
                        and existing[2] == "committed":
                    conn.rollback()
                    return {"action": "replayed", "result_kind": existing[3],
                            "result_id": int(existing[4])}
                conn.rollback(); return {"action": "conflict"}
            conn.execute(
                "INSERT INTO e4_action_reservations(reservation_id,request_id,draft_id,"
                "assessment_id,principal_ref,actor_user_id,idempotency_key_sha256,workflow_mapping,"
                "payload_sha256,quote_expires_at_epoch_ms,requested_at_epoch_ms,"
                "expires_at_epoch_ms,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?, 'reserved')",
                (value["requestId"], value["requestId"], value["draftId"],
                 value["assessmentId"], value["principalRef"], value["actorUserId"],
                 value["idempotencyKeySha256"], value["workflowMapping"],
                 value["payloadSha256"], value["quoteExpiresAtEpochMs"],
                 value["requestedAtEpochMs"], value["expiresAtEpochMs"]))
            if value["workflowMapping"] == "BUY_ORDER_CREATION":
                cursor = conn.execute(
                    "INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,"
                    "web_user_id,network,agreed_rate,agreed_crypto_amount,agreed_at) "
                    "VALUES(?,?,?,?,?,'pending',?,?,?,?,CURRENT_TIMESTAMP)",
                    (payload["user_id"], payload["username"], payload["currency"],
                     str(payload["rub_amount"]), payload["destination"],
                     payload["web_user_id"], payload["network"],
                     str(payload["agreed_rate"]), str(payload["agreed_crypto_amount"])))
                result_kind, result_id = "BUY_ORDER", int(cursor.lastrowid)
            else:
                cursor = conn.execute(
                    "INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,sbp_phone,"
                    "receive_address,status,payout_method,payout_bank,payout_details,payout_name) "
                    "VALUES(?,?,?,?,?,?,'pending',?,?,?,?)",
                    (payload["user_id"], payload["currency"], str(payload["crypto_amount"]),
                     str(payload["rub_amount"]), payload["sbp_phone"],
                     payload["receive_address"], payload["payout_method"],
                     payload["payout_bank"], payload["payout_details"], payload["payout_name"]))
                result_kind, result_id = "SELL_ORDER", int(cursor.lastrowid)
            if self.fault_after_order: self.fault_after_order()
            changed = conn.execute(
                "UPDATE e4_action_reservations SET state='committed',result_kind=?,result_id=? "
                "WHERE request_id=? AND state='reserved'",
                (result_kind, result_id, value["requestId"])).rowcount
            if changed != 1: raise RuntimeError("e4_handoff_commit_lost")
            if self.fault_before_commit: self.fault_before_commit()
            conn.commit()
            return {"action": "created", "result_kind": result_kind,
                    "result_id": result_id}


class PostgresE4ActionHandoffStore(SQLiteE4ActionHandoffStore):
    def __init__(self, dsn: str, *, fault_after_order=None, fault_before_commit=None):
        self.dsn = dsn
        self.fault_after_order, self.fault_before_commit = (
            fault_after_order, fault_before_commit)
    def _c(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)
    def handoff(self, *, reservation, draft, assessment, order):
        value = _validate_common(reservation, draft, assessment)
        payload = (_validate_buy(value, draft, order)
                   if value["workflowMapping"] == "BUY_ORDER_CREATION"
                   else _validate_sell(value, draft, order))
        with self._c() as conn:
            inserted = conn.execute(
                "INSERT INTO e4_action_reservations(reservation_id,request_id,draft_id,"
                "assessment_id,principal_ref,actor_user_id,idempotency_key_sha256,workflow_mapping,"
                "payload_sha256,quote_expires_at_epoch_ms,requested_at_epoch_ms,"
                "expires_at_epoch_ms,state) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'reserved') "
                "ON CONFLICT DO NOTHING RETURNING reservation_id",
                (value["requestId"], value["requestId"], value["draftId"],
                 value["assessmentId"], value["principalRef"], value["actorUserId"],
                 value["idempotencyKeySha256"], value["workflowMapping"],
                 value["payloadSha256"], value["quoteExpiresAtEpochMs"],
                 value["requestedAtEpochMs"], value["expiresAtEpochMs"])).fetchone()
            if not inserted:
                row = conn.execute(
                    "SELECT request_id,payload_sha256,state,result_kind,result_id FROM "
                    "e4_action_reservations WHERE draft_id=%s OR "
                    "(principal_ref=%s AND idempotency_key_sha256=%s) "
                    "ORDER BY reservation_id LIMIT 1 FOR UPDATE",
                    (value["draftId"], value["principalRef"],
                     value["idempotencyKeySha256"])).fetchone()
                if row["request_id"] == value["requestId"] \
                        and row["payload_sha256"] == value["payloadSha256"] \
                        and row["state"] == "committed":
                    return {"action": "replayed", "result_kind": row["result_kind"],
                            "result_id": int(row["result_id"])}
                return {"action": "conflict"}
            if value["workflowMapping"] == "BUY_ORDER_CREATION":
                row = conn.execute(
                    "INSERT INTO orders(user_id,username,currency,rub_amount,crypto_address,status,"
                    "web_user_id,network,agreed_rate,agreed_crypto_amount,agreed_at) "
                    "VALUES(%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s,now()) RETURNING order_id",
                    (payload["user_id"], payload["username"], payload["currency"],
                     payload["rub_amount"], payload["destination"], payload["web_user_id"],
                     payload["network"], payload["agreed_rate"],
                     payload["agreed_crypto_amount"])).fetchone()
                result_kind, result_id = "BUY_ORDER", int(row["order_id"])
            else:
                row = conn.execute(
                    "INSERT INTO sell_orders(user_id,currency,crypto_amount,rub_amount,sbp_phone,"
                    "receive_address,status,payout_method,payout_bank,payout_details,payout_name) "
                    "VALUES(%s,%s,%s,%s,%s,%s,'pending',%s,%s,%s,%s) RETURNING id",
                    (payload["user_id"], payload["currency"], payload["crypto_amount"],
                     payload["rub_amount"], payload["sbp_phone"], payload["receive_address"],
                     payload["payout_method"], payload["payout_bank"],
                     payload["payout_details"], payload["payout_name"])).fetchone()
                result_kind, result_id = "SELL_ORDER", int(row["id"])
            if self.fault_after_order: self.fault_after_order()
            conn.execute("UPDATE e4_action_reservations SET state='committed',result_kind=%s,"
                         "result_id=%s WHERE request_id=%s AND state='reserved'",
                         (result_kind, result_id, value["requestId"]))
            if self.fault_before_commit: self.fault_before_commit()
            return {"action": "created", "result_kind": result_kind,
                    "result_id": result_id}


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url: return SQLiteE4ActionHandoffStore(sqlite_path)
    if db_runtime.backend(url) != "postgresql" or os.getenv(
            "E4_ACTION_HANDOFF_POSTGRES_ENABLED", "").strip().lower() \
            not in {"1", "true", "yes"}:
        raise RuntimeError("postgres_e4_action_handoff_store_not_enabled")
    return PostgresE4ActionHandoffStore(url)
