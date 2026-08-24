"""Read-only validation for the authoritative runtime schema.

Schema creation belongs to deployment migrations.  Runtime services only prove
that the database selected for this process has the columns they require and
fail closed before background work starts when a migration is missing.
"""
from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from urllib.parse import urlparse

from core import db_runtime


_REQUIRED_COLUMNS = {
    "alert_throttle": {"key", "last_sent"},
    "alert_watermark": {"key", "value"},
    "system_flags": {"key", "value", "updated_at"},
    "audit_log": {"id", "event", "details", "created_at"},
    "provider_health": {
        "provider", "is_healthy", "last_checked", "avg_response_time",
        "failed_count", "status", "blocker",
    },
    "provider_attempts": {"provider", "ts", "success"},
    "wallet_links": {"user_id", "chain", "address", "verified_at"},
    "wallet_send_intents": {
        "id", "user_id", "chain", "sell_id", "from_address", "to_address",
        "amount", "marker", "created_at", "signed_at",
    },
    "payment_transition_audit": {
        "id", "order_id", "provider", "evidence", "from_status", "to_status",
        "action", "created_at",
    },
    "payment_notification_outbox": {
        "id", "order_id", "recipient_id", "payload", "state", "attempts",
        "created_at", "claimed_at", "sent_at", "updated_at",
    },
    "payout_reconciliations": {
        "order_id", "intent_id", "txid", "referral_btc", "vip_rub", "reconciled_at",
    },
    "notification_outbox": {
        "id", "topic", "aggregate_id", "recipient_id", "payload", "state",
        "attempts", "created_at", "claimed_at", "sent_at", "updated_at",
    },
    "client_address_notes": {
        "user_id", "currency", "network", "address", "label", "hidden", "updated_at",
    },
    "payout_shadow": {
        "order_id", "decided_at", "verdict", "detail", "provider",
        "circuit_action", "would_auto_pay", "rub_amount", "currency",
        "outcome", "outcome_at",
    },
    "order_lifecycle_work": {
        "id", "kind", "order_id", "session_token", "provider",
        "provider_invoice_id", "user_id", "currency", "rub_amount",
        "order_status", "has_receipt", "detail", "state", "attempts",
        "created_at", "claimed_at", "completed_at", "updated_at",
    },
    "payout_intents": {
        "id", "order_id", "idempotency_key", "state", "source", "requested_by",
        "rub_amount", "crypto_amount", "currency", "network", "destination",
        "attempts", "txid", "error_code", "created_at", "claimed_at",
        "finished_at", "updated_at",
    },
    "payout_intent_audit": {
        "id", "order_id", "actor", "action", "from_state", "to_state",
        "evidence", "txid", "created_at",
    },
    "referral_payout_intents": {
        "id", "user_id", "idempotency_key", "state", "crypto_amount", "currency",
        "network", "destination", "attempts", "txid", "error_code", "created_at",
        "claimed_at", "finished_at", "updated_at",
    },
    "referral_payout_intent_audit": {
        "id", "intent_id", "actor", "action", "from_state", "to_state",
        "evidence", "txid", "created_at",
    },
    "sell_settlement_ledger": {
        "sell_id", "user_id", "rub_amount", "payout_provider", "payout_ref",
        "payout_status", "settled_at",
    },
    "sell_settlement_outbox": {
        "id", "sell_id", "recipient_id", "rub_amount", "state", "attempts",
        "created_at", "claimed_at", "sent_at", "updated_at",
    },
    "order_receipts": {
        "order_id", "path", "filename", "content_type", "created_at",
        "dispute_opened_at", "sha256",
    },
    "orders": {
        "order_id", "user_id", "username", "currency", "rub_amount",
        "crypto_address", "status", "created_at", "updated_at", "network",
        "agreed_rate", "agreed_crypto_amount", "agreed_at",
        "paid_btc_tx", "web_user_id", "rub_volume_counted",
        "verification_requested", "montera_invoice_id", "receipt_sent_at",
        "receipt_deadline",
    },
    "sell_orders": {
        "id", "user_id", "currency", "crypto_amount", "rub_amount",
        "sbp_phone", "receive_address", "status", "tx_hash", "created_at",
        "updated_at", "payout_method", "payout_bank", "payout_details",
        "payout_name", "payout_provider", "payout_ref", "payout_status",
    },
    "sent_notifications": {"order_id", "event"},
}


# The Telegram process starts payment, payout, scheduled-order and customer
# notification workers immediately.  These are the tables those workers and
# the bot's user/staff routes require beyond the shared FastAPI contract.  The
# map is intentionally fixed: validation must not infer correctness from a
# database that happens to contain some similarly named legacy columns.
_BOT_REQUIRED_COLUMNS = {
    "bot_users": {
        "user_id", "username", "first_name", "last_name", "first_seen",
        "last_seen", "broadcast_enabled",
    },
    "workers": {"user_id", "username", "added_by", "added_at", "is_active"},
    "operators": {"user_id", "username", "added_by", "added_at", "is_active"},
    "blocked_users": {"user_id", "reason", "blocked_at"},
    "blocked_addresses": {"address", "reason", "blocked_by", "created_at"},
    "reserves": {"currency", "amount", "updated_at"},
    "admin_log": {"id", "admin_id", "action", "target_id", "details", "created_at"},
    "risk_events": {
        "id", "client_ip", "user_agent", "telegram_id", "event_type", "created_at",
    },
    "user_vip_volume": {"user_id", "total_rub", "updated_at"},
    "rate_subscriptions": {
        "user_id", "enabled", "last_notified", "last_btc", "last_ltc", "last_usdt",
    },
    "referral_bonuses": {
        "id", "referrer_id", "referred_id", "order_id", "bonus_amount",
        "currency", "created_at",
    },
    "reviews": {"id", "order_id", "user_id", "rating", "comment", "status", "created_at"},
    "payout_queue": {
        "id", "order_id", "btc_address", "btc_amount", "status", "txid",
        "created_at", "crypto_address", "amount", "currency",
    },
    "referrals": {
        "referrer_id", "referred_id", "bonus_paid", "created_at", "total_bonus_btc",
    },
    "referral_addresses": {"user_id", "currency", "address"},
    "rate_locks": {
        "id", "user_id", "currency", "locked_rate", "fee_rub", "locked_until",
        "used", "order_id", "created_at",
    },
    "promo_codes": {
        "id", "code", "discount_percent", "max_uses", "uses_count",
        "valid_until", "is_active", "created_at",
    },
    "promo_uses": {"code_id", "user_id", "order_id", "created_at"},
    "payment_sessions": {
        "id", "session_token", "order_id", "amount", "provider", "status",
        "provider_invoice_id", "qr_payload", "provider_payload", "client_ip",
        "user_agent", "telegram_id", "created_at", "updated_at", "expires_at",
    },
    "gift_vouchers": {
        "id", "sender_id", "currency", "rub_amount", "code", "status",
        "order_id", "recipient_id", "recipient_address", "created_at", "claimed_at",
    },
    "dca_schedules": {
        "id", "user_id", "currency", "rub_amount", "crypto_address",
        "interval_days", "runs_total", "next_run", "status",
    },
    "limit_orders": {
        "id", "user_id", "currency", "rub_amount", "crypto_address", "target_rate",
        "direction", "payment_method", "status", "expires_at",
        "triggered_at", "order_id",
    },
    "support_tickets": {
        "id", "user_id", "username", "web_user_id", "subject", "status",
        "created_at", "updated_at",
    },
    "support_messages": {"id", "ticket_id", "sender", "message", "created_at"},
    "swap_sessions": {
        "id", "session_token", "user_id", "coin_from", "coin_to", "amount_from",
        "address_to", "trocador_id", "trocador_url", "status", "web_user_id",
        "provider", "deposit_address", "created_at", "updated_at",
    },
    "bot_notification_jobs": {
        "id", "kind", "dedupe_key", "payload", "state", "attempts",
        "created_at", "claimed_at", "sent_at", "updated_at",
    },
}


def _required(profile: str) -> dict[str, set[str]]:
    if profile not in {"shared", "bot"}:
        raise ValueError("invalid_runtime_schema_profile")
    required = {table: set(columns) for table, columns in _REQUIRED_COLUMNS.items()}
    if profile == "bot":
        for table, columns in _BOT_REQUIRED_COLUMNS.items():
            required.setdefault(table, set()).update(columns)
    return required


def _incomplete(actual: dict[str, set[str]], required: dict[str, set[str]]) -> RuntimeError | None:
    missing = []
    for table, columns in required.items():
        absent = sorted(columns - actual.get(table, set()))
        if absent:
            missing.append(f"{table}({','.join(absent)})")
    if missing:
        return RuntimeError("database_schema_incomplete:" + ";".join(missing))
    return None


class SQLiteRuntimeSchemaStore:
    def __init__(self, path: str, *, timeout: float = 5):
        self.path, self.timeout = path, timeout

    def validate(self, *, profile: str = "shared") -> None:
        required = _required(profile)
        actual = {}
        target = self.path
        if target.startswith("sqlite:///"):
            target = urlparse(target).path
        uri = Path(target).resolve().as_uri() + "?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=self.timeout) as conn:
                conn.execute(f"PRAGMA busy_timeout={int(self.timeout * 1000)}")
                for table in required:
                    actual[table] = {str(row[1]) for row in conn.execute(
                        f"PRAGMA table_info({table})"
                    ).fetchall()}
        except sqlite3.Error as exc:
            raise RuntimeError("database_schema_unavailable") from exc
        error = _incomplete(actual, required)
        if error:
            raise error


class PostgresRuntimeSchemaStore:
    def __init__(self, dsn: str):
        self.dsn = dsn

    def validate(self, *, profile: str = "shared") -> None:
        import psycopg

        required = _required(profile)
        actual = {}
        with psycopg.connect(self.dsn) as conn, conn.cursor() as cur:
            for table in required:
                cur.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema=current_schema() AND table_name=%s",
                    (table,),
                )
                actual[table] = {str(row[0]) for row in cur.fetchall()}
        error = _incomplete(actual, required)
        if error:
            raise error


def from_environment(*, sqlite_path: str):
    url = os.getenv("DATABASE_URL", "").strip()
    if not url:
        return SQLiteRuntimeSchemaStore(sqlite_path)
    if db_runtime.backend(url) != "postgresql":
        raise RuntimeError("unsupported_authoritative_database")
    return PostgresRuntimeSchemaStore(url)
