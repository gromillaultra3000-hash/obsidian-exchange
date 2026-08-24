import os
import shutil
import subprocess
import sys
import tempfile
import pytest
from pathlib import Path


RELAY_ADMIN = os.getenv("E04_RELAY_ADMIN_DSN")
BOT_ADMIN = os.getenv("E04_BOT_ADMIN_DSN")
if not RELAY_ADMIN or not BOT_ADMIN:
    pytest.skip("E04_RELAY_ADMIN_DSN/E04_BOT_ADMIN_DSN unset", allow_module_level=True)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]


def restricted(dsn, user):
    parts = conninfo_to_dict(dsn)
    parts.update(user=user, password="synthetic-rehearsal-only", connect_timeout="2")
    return make_conninfo(**parts)


with tempfile.TemporaryDirectory(prefix="e04-pg-adapter-") as td:
    candidate = Path(td) / "candidate"
    layout = Path(td) / "layout"
    subprocess.run([
        sys.executable, str(ROOT / "scripts/e0_4_build_owner_auth_candidate.py"),
        "--relay-base", "/opt/obsidian-exchange/relay-fastapi/main.py",
        "--relay-source", str(ROOT / "relay-fastapi/main.py"),
        "--bot-base", "/opt/obsidian-exchange/bot/main_bot.py",
        "--bot-source", str(ROOT / "bot/main_bot.py"),
        "--output-dir", str(candidate),
    ], check=True, capture_output=True, text=True)
    shutil.copytree("/opt/obsidian-exchange/relay", layout,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log", ".env", "*.db"))
    for source in (candidate / "relay").rglob("*.py"):
        target = layout / source.relative_to(candidate / "relay")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    sys.path.insert(0, str(layout))

    from repositories.engagement_store import PostgresEngagementStore
    from repositories.order_read_store import PostgresOrderReadStore
    from repositories.payment_session_store import PostgresPaymentSessionStore
    from repositories.receipt_store import PostgresReceiptStore

    relay_dsn = restricted(RELAY_ADMIN, "obsidian_relay")
    os.environ["RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED"] = "1"
    orders = PostgresOrderReadStore(relay_dsn)
    sessions = PostgresPaymentSessionStore(relay_dsn)
    receipts = PostgresReceiptStore(relay_dsn)
    assert orders.authorized_snapshot(1, user_id=7)["crypto_address"] == "owner-destination"
    assert orders.authorized_snapshot(1, user_id=8) is None
    assert orders.authorized_snapshot(1, session_token="owner-token")["user_id"] == 7
    assert sessions.get_by_token("owner-token")["order_id"] == 1
    assert sessions.latest_for_authorized_order(1, user_id=7)["session_token"] == "owner-token"
    assert sessions.latest_active_for_authorized_order(1, session_token="owner-token")["session_token"] == "owner-token"
    assert sessions.latest_provider_invoice_for_authorized_order(
        1, "brabus", user_id=7, prefix=True)["provider_invoice_id"] == "owner-invoice"
    assert receipts.authorized_state(1, user_id=7) == "stored"
    assert receipts.authorized_state(2, user_id=7) == ""

    os.environ["RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED"] = "0"
    try:
        orders.authorized_snapshot(1, user_id=7)
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("Relay direct-SQL fallback unexpectedly worked under execute-only ACL")

    with psycopg.connect(BOT_ADMIN) as conn:
        conn.execute("DELETE FROM reviews WHERE order_id IN (103,104)")
        conn.execute("DELETE FROM orders WHERE order_id IN (103,104)")
        conn.execute("INSERT INTO orders(order_id,user_id,status) VALUES(103,7,'sent'),(104,8,'sent')")
        conn.execute("INSERT INTO reviews(order_id,user_id,rating,status) VALUES(103,7,5,'pending_comment'),(104,7,5,'pending_comment')")
    bot_dsn = restricted(BOT_ADMIN, "obsidian_exchange_bot")
    os.environ["BOT_B3_ENGAGEMENT_ACL_ADAPTER_ENABLED"] = "1"
    engagement = PostgresEngagementStore(bot_dsn)
    assert engagement.comment_review(103, 8, "foreign") is False
    assert engagement.finalize_review(103, 8) is None
    assert engagement.comment_review(104, 7, "inconsistent-order-owner") is False
    assert engagement.finalize_review(104, 7) is None
    assert engagement.comment_review(103, 7, "owner") is True
    result = engagement.finalize_review(103, 7)
    assert result == {"user_id":7, "rating":5, "comment":"owner", "status":"published"}
    assert engagement.finalize_review(103, 7) is None

    os.environ["BOT_B3_ENGAGEMENT_ACL_ADAPTER_ENABLED"] = "0"
    try:
        engagement.comment_review(104, 7, "direct")
    except psycopg.errors.InsufficientPrivilege:
        pass
    else:
        raise AssertionError("Bot direct-SQL fallback unexpectedly worked under execute-only ACL")

    with psycopg.connect(BOT_ADMIN) as conn:
        assert conn.execute("SELECT status,comment FROM reviews WHERE order_id=104").fetchone() == (
            "pending_comment", None)

print("E0.4 candidate execute-only PostgreSQL adapters: OK")
