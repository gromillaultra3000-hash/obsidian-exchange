import asyncio
import hashlib
import hmac
import json
import os
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.parse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def signed_init_data(token, user_id):
    values = {"auth_date":str(int(time.time())), "query_id":f"candidate-{user_id}",
              "user":json.dumps({"id":user_id}, separators=(",", ":"))}
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(values)


def forbidden(*args, **kwargs):
    raise AssertionError("network or money-writer effect attempted")


def run():
    with tempfile.TemporaryDirectory(prefix="e04-candidate-runtime-") as td:
        temp = Path(td)
        layout, built = temp / "layout", temp / "built"
        layout.mkdir(mode=0o700)
        shutil.copytree("/opt/obsidian-exchange/relay-fastapi", layout / "relay-fastapi",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log", ".env", "*.db"))
        shutil.copytree("/opt/obsidian-exchange/relay", layout / "relay",
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.log", ".env", "*.db"))
        subprocess.run([
            sys.executable, str(ROOT / "scripts/e0_4_build_owner_auth_candidate.py"),
            "--relay-base", "/opt/obsidian-exchange/relay-fastapi/main.py",
            "--relay-source", str(ROOT / "relay-fastapi/main.py"),
            "--bot-base", "/opt/obsidian-exchange/bot/main_bot.py",
            "--bot-source", str(ROOT / "bot/main_bot.py"),
            "--output-dir", str(built),
        ], check=True, capture_output=True, text=True)
        for source in built.rglob("*.py"):
            relative = source.relative_to(built)
            if relative.parts[0] == "bot":
                continue
            target = layout / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)

        db_path = temp / "unused.db"
        os.environ.update({
            "DB_PATH":str(db_path), "DATABASE_URL":"", "BOT_TOKEN":"candidate-hmac-token",
            "RELAY_SECRET":"candidate-relay-secret", "RELAY_BACKGROUND_TASKS_ENABLED":"0",
            "ADMIN_CONFIG_POSTGRES_ENABLED":"false", "ORDER_RUNTIME_POSTGRES_ENABLED":"false",
            "PAYOUT_POSTGRES_ENABLED":"false", "SHADOW_PAYOUT_POSTGRES_ENABLED":"false",
        })
        sys.path.insert(0, str(layout / "relay"))
        sys.path.insert(0, str(layout / "relay-fastapi"))
        original = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection)
        socket.socket.connect = forbidden
        socket.socket.connect_ex = forbidden
        socket.create_connection = forbidden
        try:
            import main
            import httpx
            from core import order_access
            from repositories.engagement_store import SQLiteEngagementStore

            class Orders:
                def authorized_snapshot(self, order_id, *, user_id=None, session_token=None):
                    owner = {1:7, 2:8}.get(int(order_id))
                    token_owner = {"owner-token":7, "other-token":8}.get(session_token)
                    if owner is None or (user_id != owner and token_owner != owner):
                        return None
                    return {"order_id":order_id, "user_id":owner, "status":"sent",
                            "paid_btc_tx":None, "verification_requested":None,
                            "currency":"BTC", "network":"bitcoin", "rub_amount":1000}

            class Sessions:
                def latest_provider_invoice_for_authorized_order(self, *args, **kwargs):
                    raise AssertionError("provider polling must not run for terminal synthetic order")
                def latest_active_for_authorized_order(self, order_id, *, user_id=None, session_token=None):
                    if int(order_id) == 1 and user_id == 7:
                        return {"session_token":"owner-token"}
                    return None
                def get_by_token(self, token):
                    if token != "owner-token":
                        return None
                    return {"amount":1000, "order_id":1, "status":"invoice_created",
                            "provider_payload":"{}", "qr_payload":"", "expires_at":""}

            class Receipts:
                def authorized_state(self, order_id, *, user_id=None, session_token=None):
                    assert (int(order_id), user_id, session_token) in {
                        (1, 7, None), (1, None, "owner-token")}
                    return ""

            main._order_reads = Orders()
            main._payment_sessions = Sessions()
            main._receipts = Receipts()
            main._mark_order_paid = forbidden
            audits = []
            main.audit_log = lambda *args, **kwargs: audits.append((args, kwargs))
            main._payout_delayed = lambda order_id: False
            main.BOT_TOKEN = "candidate-hmac-token"
            main.SECRET_KEY = "candidate-relay-secret"
            db_before = hashlib.sha256(db_path.read_bytes()).hexdigest() if db_path.exists() else None

            async def route_checks():
                transport = httpx.ASGITransport(app=main.app)
                async with httpx.AsyncClient(transport=transport,
                                             base_url="https://synthetic.invalid") as client:
                    owner = {"X-Telegram-Init-Data":signed_init_data(main.BOT_TOKEN, 7)}
                    foreign = {"X-Telegram-Init-Data":signed_init_data(main.BOT_TOKEN, 8)}
                    assert (await client.get("/api/order/1", headers=owner)).status_code == 200
                    assert (await client.get("/api/order/1", headers=foreign)).status_code == 404
                    assert (await client.get("/api/order/1?token=other-token", headers=owner)).status_code == 200
                    assert (await client.get("/api/order/1?token=owner-token", headers=foreign)).status_code == 404
                    assert (await client.get("/api/order/1?user_id=8", headers=owner)).status_code == 200
                    assert (await client.get("/api/order/1?token=owner-token")).status_code == 200
                    assert (await client.get("/api/order/1?token=other-token")).status_code == 404
                    assert (await client.get("/api/order/1?key=candidate-relay-secret&user_id=7")).status_code == 200
                    assert (await client.get("/api/order/1?key=candidate-relay-secret")).status_code == 404
                    assert (await client.get("/api/order/1?key=candidate-relay-secret&user_id=8")).status_code == 404
                    assert (await client.get("/api/order/1")).status_code == 404

                    proof = order_access.issue(1, 7)
                    valid = await client.get("/pay/1", params={"proof":proof}, follow_redirects=False)
                    assert valid.status_code == 302 and valid.headers["location"] == "/pay/owner-token"
                    assert (await client.get("/pay/1")).status_code == 404
                    assert (await client.get("/pay/2", params={"proof":proof})).status_code == 404
                    expired = order_access.issue(1, 7, now=1_000)
                    assert (await client.get("/pay/1", params={"proof":expired})).status_code == 404
                    opaque = await client.get("/pay/owner-token")
                    assert opaque.status_code == 200 and "Заявка #1" in opaque.text
                    assert (await client.get("/pay/other-token")).status_code == 404

            asyncio.run(route_checks())
            assert len(audits) == 2

            review_db = temp / "review.db"
            with sqlite3.connect(review_db) as conn:
                conn.executescript("""
                CREATE TABLE reviews(id INTEGER PRIMARY KEY,order_id INTEGER UNIQUE,user_id INTEGER,
                  rating INTEGER,comment TEXT,status TEXT,created_at TEXT);
                CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER);
                INSERT INTO orders VALUES(11,7);
                INSERT INTO reviews VALUES(1,11,7,5,NULL,'pending_comment','2026-08-17');
                """)
            engagement = SQLiteEngagementStore(str(review_db))
            assert engagement.comment_review(11, 8, "foreign") is False
            assert engagement.finalize_review(11, 8) is None
            assert engagement.comment_review(11, 7, "owner") is True
            assert engagement.finalize_review(11, 7)["status"] == "published"
        finally:
            socket.socket.connect, socket.socket.connect_ex, socket.create_connection = original
        db_after = hashlib.sha256(db_path.read_bytes()).hexdigest() if db_path.exists() else None
        assert db_after == db_before
        assert not Path(str(db_path) + "-wal").exists()


def test_candidate_runtime_matrix_in_fresh_subprocess():
    subprocess.run(["/opt/obsidian-exchange/relay-venv/bin/python", str(Path(__file__)),
                    "--isolated-child"], check=True, timeout=45)


if __name__ == "__main__":
    if sys.argv[1:] == ["--isolated-child"]:
        run()
    else:
        test_candidate_runtime_matrix_in_fresh_subprocess()
    print("E0.4 owner/auth candidate runtime matrix: OK")
