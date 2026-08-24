"""Single-winner durable reservation for E4 private action drafts."""

from __future__ import annotations

import os
from typing import Any, Callable, Protocol

from core import db_runtime
from core.e4_action_reservation import validate_action_reservation_request


class E4ActionReservationStore(Protocol):
    def reserve(self, request: dict[str, Any]) -> dict[str, Any]: ...


def _row_result(row, request: dict[str, Any], *, inserted: bool) -> dict[str, Any]:
    fields = ("reservation_id", "request_id", "draft_id", "assessment_id",
              "principal_ref", "actor_user_id", "idempotency_key_sha256", "workflow_mapping",
              "payload_sha256", "quote_expires_at_epoch_ms",
              "requested_at_epoch_ms", "expires_at_epoch_ms")
    data = dict(zip(fields, row)) if not isinstance(row, dict) else dict(row)
    exact = all(data[name] == request[source] for name, source in (
        ("reservation_id", "requestId"), ("request_id", "requestId"),
        ("draft_id", "draftId"), ("assessment_id", "assessmentId"),
        ("principal_ref", "principalRef"),
        ("actor_user_id", "actorUserId"),
        ("idempotency_key_sha256", "idempotencyKeySha256"),
        ("workflow_mapping", "workflowMapping"), ("payload_sha256", "payloadSha256"),
        ("quote_expires_at_epoch_ms", "quoteExpiresAtEpochMs"),
        ("requested_at_epoch_ms", "requestedAtEpochMs"),
        ("expires_at_epoch_ms", "expiresAtEpochMs")))
    if not exact:
        return {"action": "conflict", "reservation_id": data["reservation_id"]}
    return {"action": "reserved" if inserted else "replayed",
            "reservation_id": data["reservation_id"]}


class SQLiteE4ActionReservationStore:
    def __init__(self, path: str, *, timeout: float = 10,
                 fault_after_insert: Callable[[], None] | None = None):
        self.path, self.timeout = path, timeout
        self.fault_after_insert = fault_after_insert

    def _connect(self):
        return db_runtime.sqlite_connect(self.path, timeout=self.timeout)

    def reserve(self, request: dict[str, Any]) -> dict[str, Any]:
        value = validate_action_reservation_request(request)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT reservation_id,request_id,draft_id,assessment_id,principal_ref,actor_user_id,"
                "idempotency_key_sha256,workflow_mapping,payload_sha256,"
                "quote_expires_at_epoch_ms,requested_at_epoch_ms,expires_at_epoch_ms "
                "FROM e4_action_reservations "
                "WHERE draft_id=? OR (principal_ref=? AND idempotency_key_sha256=?) LIMIT 1",
                (value["draftId"], value["principalRef"],
                 value["idempotencyKeySha256"])).fetchone()
            if row:
                conn.rollback()
                return _row_result(row, value, inserted=False)
            conn.execute(
                "INSERT INTO e4_action_reservations(reservation_id,request_id,draft_id,"
                "assessment_id,principal_ref,actor_user_id,idempotency_key_sha256,workflow_mapping,"
                "payload_sha256,quote_expires_at_epoch_ms,requested_at_epoch_ms,"
                "expires_at_epoch_ms,state) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,'reserved')",
                (value["requestId"], value["requestId"], value["draftId"],
                 value["assessmentId"], value["principalRef"], value["actorUserId"],
                 value["idempotencyKeySha256"], value["workflowMapping"],
                 value["payloadSha256"], value["quoteExpiresAtEpochMs"],
                 value["requestedAtEpochMs"],
                 value["expiresAtEpochMs"]))
            if self.fault_after_insert:
                self.fault_after_insert()
            conn.commit()
            return {"action": "reserved", "reservation_id": value["requestId"]}


class PostgresE4ActionReservationStore:
    def __init__(self, dsn: str): self.dsn = dsn
    def _connect(self):
        import psycopg
        from psycopg.rows import dict_row
        return psycopg.connect(self.dsn, row_factory=dict_row)

    def reserve(self, request: dict[str, Any]) -> dict[str, Any]:
        value = validate_action_reservation_request(request)
        with self._connect() as conn:
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
                 value["requestedAtEpochMs"],
                 value["expiresAtEpochMs"])).fetchone()
            row = conn.execute(
                "SELECT reservation_id,request_id,draft_id,assessment_id,principal_ref,actor_user_id,"
                "idempotency_key_sha256,workflow_mapping,payload_sha256,"
                "quote_expires_at_epoch_ms,requested_at_epoch_ms,expires_at_epoch_ms "
                "FROM e4_action_reservations "
                "WHERE draft_id=%s OR (principal_ref=%s AND idempotency_key_sha256=%s) "
                "ORDER BY reservation_id LIMIT 1 FOR UPDATE",
                (value["draftId"], value["principalRef"],
                 value["idempotencyKeySha256"])).fetchone()
            return _row_result(row, value, inserted=inserted is not None)


def from_environment(*, sqlite_path: str) -> E4ActionReservationStore:
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteE4ActionReservationStore(sqlite_path)
    if db_runtime.backend(url) != "postgresql" or os.getenv(
            "E4_ACTION_RESERVATION_POSTGRES_ENABLED", "").strip().lower() \
            not in {"1", "true", "yes"}:
        raise RuntimeError("postgres_e4_action_reservation_store_not_enabled")
    return PostgresE4ActionReservationStore(url)
