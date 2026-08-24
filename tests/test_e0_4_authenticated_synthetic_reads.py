import hashlib
import hmac
import asyncio
import json
import os
import subprocess
import socket
import sqlite3
import sys
import tempfile
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def signed_init_data(token: str, user_id: int) -> str:
    values = {
        "auth_date": str(int(time.time())),
        "query_id": f"synthetic-{user_id}",
        "user": json.dumps({"id": user_id, "first_name": f"user-{user_id}"},
                           separators=(",", ":")),
    }
    check = "\n".join(f"{key}={value}" for key, value in sorted(values.items()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(values)


class FakeTemplates:
    def TemplateResponse(self, request, name, context=None, status_code=200):
        from fastapi.responses import JSONResponse
        body = {key: value for key, value in (context or {}).items()
                if key != "request"}
        body["template"] = name
        return JSONResponse(body, status_code=status_code)


class OrderReads:
    def customer_orders(self, user_id, limit):
        return [{
            "order_id": 7000 + user_id,
            "rub_amount": 1000 + user_id,
            "currency": "BTC",
            "status": "sent",
            "created_at": "2026-08-17T00:00:00Z",
            "session_token": f"owner-session-{user_id}",
            "paid_btc_tx": None,
            "receipt_sent_at": None,
            "network": "bitcoin",
        }]

    def receipt_order_ids(self, order_ids):
        list(order_ids)
        return set()


class EngagementReads:
    def referral_stats(self, user_id):
        return {"referrals": user_id, "active": user_id + 1,
                "total_bonus_btc": user_id / 100000000}


class SupportReads:
    def list_for_web_user(self, web_user_id):
        return [{"id": 9000 + web_user_id, "subject": f"owner-{web_user_id}",
                 "status": "open", "created_at": "x", "updated_at": "x"}]

    def thread_for_web_user(self, ticket_id, web_user_id):
        if ticket_id != 9000 + web_user_id:
            return None
        return {"ticket": {"id": ticket_id, "subject": f"owner-{web_user_id}"},
                "messages": []}

    def __getattr__(self, name):
        raise AssertionError(f"support writer or unexpected method called: {name}")


class SellReads:
    def pending_view_for_user(self, user_id, status, limit):
        assert status == "pending" and limit == 10
        return [{
            "id": 8000 + user_id, "currency": "BTC", "crypto_amount": 0.01,
            "rub_amount": 1000 + user_id, "payout_method": "sbp",
            "payout_details": f"owner-{user_id}", "payout_bank": "",
            "sbp_phone": "", "receive_address": "bc1qsynthetic",
            "created_at": "2026-08-17T00:00:00Z",
        }]

    def __getattr__(self, name):
        raise AssertionError(f"sell writer or unexpected method called: {name}")


class ForbiddenEffect:
    def __getattr__(self, name):
        raise AssertionError(f"effectful dependency called: {name}")


def forbidden_call(*args, **kwargs):
    raise AssertionError("effectful or external call attempted")


def run():
    with tempfile.TemporaryDirectory(prefix="e04-auth-") as temp:
        db_path = str(Path(temp) / "synthetic.db")
        os.environ.update({
            "DB_PATH": db_path,
            "DATABASE_URL": "",
            "BOT_TOKEN": "synthetic-e04-bot-token",
            "OBSIDIAN_SKIP_DOTENV": "1",
            "RELAY_BACKGROUND_TASKS_ENABLED": "0",
            "ADMIN_CONFIG_POSTGRES_ENABLED": "false",
            "ORDER_RUNTIME_POSTGRES_ENABLED": "false",
            "PAYOUT_POSTGRES_ENABLED": "false",
            "SHADOW_PAYOUT_POSTGRES_ENABLED": "false",
        })
        sys.path.insert(0, str(ROOT / "relay"))
        sys.path.insert(0, str(ROOT / "relay-fastapi"))

        original_connect = socket.socket.connect
        original_connect_ex = socket.socket.connect_ex
        original_create_connection = socket.create_connection
        socket.socket.connect = forbidden_call
        socket.socket.connect_ex = forbidden_call
        socket.create_connection = forbidden_call

        import main
        from repositories.web_auth_store import SQLiteWebAuthStore
        import httpx

        with sqlite3.connect(db_path) as conn:
            conn.executescript("""
                CREATE TABLE web_users(
                  id INTEGER PRIMARY KEY,email TEXT NOT NULL UNIQUE,
                  password_hash TEXT NOT NULL,telegram_id INTEGER UNIQUE,
                  telegram_username TEXT,created_at TEXT,
                  totp_secret TEXT,totp_enabled INTEGER DEFAULT 0);
                CREATE TABLE web_sessions(
                  token TEXT PRIMARY KEY,web_user_id INTEGER NOT NULL,
                  csrf_token TEXT NOT NULL,created_at TEXT,
                  expires_at TEXT NOT NULL);
            """)
            expires = (datetime.now(timezone.utc) + timedelta(hours=1)).strftime(
                "%Y-%m-%d %H:%M:%S")
            conn.executemany(
                "INSERT INTO web_users(id,email,password_hash,telegram_id,telegram_username) "
                "VALUES(?,?,?,?,?)",
                [(70, "owner70@example.test", "unused", 7, "owner70"),
                 (80, "owner80@example.test", "unused", 8, "owner80")],
            )
            conn.executemany(
                "INSERT INTO web_sessions(token,web_user_id,csrf_token,expires_at) "
                "VALUES(?,?,?,?)",
                [("session-70", 70, "csrf-70", expires),
                 ("session-80", 80, "csrf-80", expires)],
            )

        main.auth._store = SQLiteWebAuthStore(db_path)
        assert main.BOT_TOKEN == "synthetic-e04-bot-token"
        assert main.DB_PATH == db_path
        assert main.os.environ.get("DATABASE_URL") == ""
        assert main._SKIP_DOTENV is True
        main.templates = FakeTemplates()
        main.site_context = lambda request, **values: {"request": request, **values}
        main.get_user_orders = lambda user, limit: [f"orders-owner-{user['id']}"]
        main.get_user_swaps = lambda user, limit: [f"swaps-owner-{user['id']}"]
        main.get_user_sell_orders = lambda user, limit: [f"sells-owner-{user['id']}"]
        main._order_reads = OrderReads()
        main._engagement = EngagementReads()
        main._support_store = SupportReads()
        main._sell_store = SellReads()
        main._delayed_ids = lambda: set()
        main.exchange_calc.get_cached_rate = lambda currency: 1000000
        main._sell_assets.can_mark = lambda currency: False
        main._sell_assets.networks_for = lambda currency: ["bitcoin"]
        main._sell_assets.network_of = lambda currency, address: "bitcoin"
        main._assets.networks_for = lambda currency: ["bitcoin"]
        main._order_workflow = ForbiddenEffect()
        main._order_store = ForbiddenEffect()
        main._payment_store = ForbiddenEffect()
        main._payment_sessions = ForbiddenEffect()
        main._order_lifecycle = ForbiddenEffect()
        main._swap_store = ForbiddenEffect()
        main._ops_store = ForbiddenEffect()
        main._sell_settlement = ForbiddenEffect()
        main.payment_service = ForbiddenEffect()
        main.notify_telegram = forbidden_call
        main.notify_admins_tg = forbidden_call

        before = hashlib.sha256(Path(db_path).read_bytes()).hexdigest()

        async def checks():
          transport = httpx.ASGITransport(app=main.app)
          async with httpx.AsyncClient(transport=transport,
                                      base_url="https://synthetic.invalid") as client:
           for web_id in (70, 80):
            cookies = {main.auth.SESSION_COOKIE: f"session-{web_id}"}
            orders = await client.get("/dashboard/orders", cookies=cookies)
            assert orders.status_code == 200
            assert f"orders-owner-{web_id}" in orders.text
            assert f"orders-owner-{150-web_id}" not in orders.text

            support = await client.get("/dashboard/support", cookies=cookies)
            assert support.status_code == 200
            assert f"owner-{web_id}" in support.text
            assert f"owner-{150-web_id}" not in support.text
            assert (await client.get(f"/dashboard/support/{9000 + 150 - web_id}",
                                     cookies=cookies)).status_code == 404

            referral = await client.get("/dashboard/referral", cookies=cookies)
            assert referral.status_code == 200
            assert f"ref_{web_id // 10}" in referral.text
            assert referral.json()["stats"]["referrals"] == web_id // 10

           for telegram_id in (7, 8):
            header = {"X-Telegram-Init-Data": signed_init_data(main.BOT_TOKEN, telegram_id)}
            other = 15 - telegram_id
            history = await client.get(f"/api/history?user_id={other}", headers=header)
            assert history.status_code == 200
            assert history.json()[0]["order_id"] == 7000 + telegram_id
            assert str(7000 + other) not in history.text

            referrals = await client.get(f"/api/referral_stats?user_id={other}", headers=header)
            assert referrals.status_code == 200
            assert referrals.json()["referrals"] == telegram_id

            pending = await client.get(f"/api/sell/pending?user_id={other}", headers=header)
            assert pending.status_code == 200
            assert pending.json()["items"][0]["sell_id"] == 8000 + telegram_id
            assert str(8000 + other) not in pending.text

           assert (await client.get("/api/history")).status_code == 403
           assert (await client.get("/api/referral_stats", headers={
            "X-Telegram-Init-Data": "auth_date=1&user=%7B%22id%22%3A7%7D&hash=bad"
           })).status_code == 403

        try:
            asyncio.run(checks())
        finally:
            socket.socket.connect = original_connect
            socket.socket.connect_ex = original_connect_ex
            socket.create_connection = original_create_connection

        after = hashlib.sha256(Path(db_path).read_bytes()).hexdigest()
        assert after == before
        assert not Path(db_path + "-wal").exists()


def test_e0_4_authenticated_reads_in_fresh_subprocess():
    subprocess.run(
        ["/opt/obsidian-exchange/relay-venv/bin/python", str(Path(__file__)),
         "--isolated-child"],
        check=True,
        timeout=30,
    )


if __name__ == "__main__":
    if sys.argv[1:] == ["--isolated-child"]:
        run()
    else:
        test_e0_4_authenticated_reads_in_fresh_subprocess()
    print("E0.4 authenticated synthetic read checks: OK")
