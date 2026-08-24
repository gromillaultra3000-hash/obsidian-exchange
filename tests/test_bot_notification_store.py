import json
import sqlite3
import sys
import tempfile
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.bot_notification_store import SQLiteBotNotificationStore


NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)


def stamp(delta):
    return (NOW + delta).strftime("%Y-%m-%d %H:%M:%S")


BASE_SCHEMA = """
CREATE TABLE orders(
 order_id INTEGER PRIMARY KEY,user_id INTEGER NOT NULL,currency TEXT NOT NULL,
 rub_amount REAL NOT NULL,crypto_address TEXT NOT NULL,status TEXT NOT NULL,
 created_at TEXT NOT NULL,updated_at TEXT,paid_btc_tx TEXT,montera_invoice_id TEXT,
 receipt_deadline TEXT,receipt_sent_at TEXT);
CREATE TABLE sent_notifications(
 order_id INTEGER,event TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
 PRIMARY KEY(order_id,event));
CREATE TABLE promo_codes(
 id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,discount_percent REAL,
 max_uses INTEGER,uses_count INTEGER DEFAULT 0,valid_until TEXT,is_active INTEGER);
CREATE TABLE order_receipts(
 order_id INTEGER PRIMARY KEY,path TEXT,filename TEXT,content_type TEXT,created_at TEXT);
CREATE TABLE payment_sessions(
 id INTEGER PRIMARY KEY AUTOINCREMENT,session_token TEXT UNIQUE,order_id INTEGER,
 status TEXT,created_at TEXT);
CREATE TABLE blocked_users(user_id INTEGER PRIMARY KEY,reason TEXT);
"""


def order(conn, oid, uid, status, *, created, updated=None, currency="BTC", rub=2500,
          txid=None, invoice=None, deadline=None, receipt_sent=None):
    conn.execute(
        "INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status,"
        "created_at,updated_at,paid_btc_tx,montera_invoice_id,receipt_deadline,receipt_sent_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (oid, uid, currency, rub, "bc1qtest", status, created, updated, txid,
         invoice, deadline, receipt_sent),
    )


with tempfile.TemporaryDirectory() as td:
    path = str(Path(td) / "notifications.db")
    with sqlite3.connect(path) as conn:
        conn.executescript(BASE_SCHEMA)
        conn.executescript((ROOT / "deploy/sqlite/023_bot_notification_jobs.sql").read_text())

        # Recall: historical sent customer, no order for 14 days. A historical
        # marker is lifetime-scoped; a recent order excludes another customer.
        order(conn, 1001, 101, "sent", created=stamp(timedelta(days=-30)))
        order(conn, 1002, 102, "sent", created=stamp(timedelta(days=-30)))
        order(conn, 1003, 102, "expired", created=stamp(timedelta(days=-2)))
        order(conn, 1004, 103, "sent", created=stamp(timedelta(days=-30)))
        conn.execute(
            "INSERT INTO sent_notifications(order_id,event,created_at) VALUES(103,'recall',?)",
            (stamp(timedelta(days=-100)),),
        )

        # Montera snapshots receipt existence at claim time.
        order(conn, 2001, 201, "pending", created=stamp(timedelta(minutes=-5)),
              invoice="m-file", deadline=stamp(timedelta(minutes=10)))
        conn.execute(
            "INSERT INTO order_receipts VALUES(2001,'/r','r.pdf','application/pdf',?)",
            (stamp(timedelta(minutes=-1)),),
        )
        order(conn, 2002, 202, "pending", created=stamp(timedelta(minutes=-5)),
              invoice="m-empty", deadline=stamp(timedelta(minutes=9)))
        order(conn, 2003, 203, "pending", created=stamp(timedelta(minutes=-5)),
              invoice="too-late", deadline=stamp(timedelta(minutes=13)))

        # Abandoned: no receipt and the latest non-dead session is retained.
        order(conn, 3001, 301, "pending", created=stamp(timedelta(minutes=-10)))
        conn.execute(
            "INSERT INTO payment_sessions(session_token,order_id,status,created_at) "
            "VALUES('live-old',3001,'awaiting_payment',?)",
            (stamp(timedelta(minutes=-10)),),
        )
        conn.execute(
            "INSERT INTO payment_sessions(session_token,order_id,status,created_at) "
            "VALUES('dead-newer',3001,'failed',?)",
            (stamp(timedelta(minutes=-9)),),
        )
        conn.execute(
            "INSERT INTO payment_sessions(session_token,order_id,status,created_at) "
            "VALUES('live-latest',3001,'invoice_created',?)",
            (stamp(timedelta(minutes=-8)),),
        )
        order(conn, 3002, 302, "pending", created=stamp(timedelta(minutes=-10)))
        conn.execute(
            "INSERT INTO order_receipts VALUES(3002,'/r2','r2.pdf','application/pdf',?)",
            (stamp(timedelta(minutes=-1)),),
        )

        # Payout delay uses the shared warning age and excludes completed txids.
        order(conn, 4001, 401, "paid", created=stamp(timedelta(hours=-2)),
              updated=stamp(timedelta(minutes=-50)), currency="LTC")
        order(conn, 4002, 402, "paid", created=stamp(timedelta(hours=-2)),
              updated=stamp(timedelta(minutes=-20)))
        order(conn, 4003, 403, "paid", created=stamp(timedelta(hours=-2)),
              updated=stamp(timedelta(minutes=-50)), txid="known")

        # Winback: one valid user plus paid, receipt, prior-marker and blocked
        # exclusions. The selected order is the latest eligible expired one.
        order(conn, 5001, 501, "expired", created=stamp(timedelta(hours=-4)),
              updated=stamp(timedelta(hours=-3)))
        order(conn, 5002, 501, "expired", created=stamp(timedelta(hours=-3)),
              updated=stamp(timedelta(hours=-2)))
        order(conn, 5011, 511, "expired", created=stamp(timedelta(hours=-3)),
              updated=stamp(timedelta(hours=-2)))
        order(conn, 5012, 511, "sent", created=stamp(timedelta(days=-10)))
        order(conn, 5021, 521, "expired", created=stamp(timedelta(hours=-3)),
              updated=stamp(timedelta(hours=-2)))
        conn.execute(
            "INSERT INTO order_receipts VALUES(5021,'/r3','r3.pdf','application/pdf',?)",
            (stamp(timedelta(hours=-2)),),
        )
        order(conn, 5031, 531, "expired", created=stamp(timedelta(hours=-3)),
              updated=stamp(timedelta(hours=-2)))
        conn.execute(
            "INSERT INTO sent_notifications(order_id,event) VALUES(5031,'winback_promo')")
        order(conn, 5041, 541, "expired", created=stamp(timedelta(hours=-3)),
              updated=stamp(timedelta(hours=-2)))
        conn.execute("INSERT INTO blocked_users VALUES(541,'blocked')")

    store = SQLiteBotNotificationStore(path)
    assert store.queue_due_recalls(now=NOW) == 1
    assert store.queue_due_montera(now=NOW) == 2
    assert store.queue_due_abandoned(now=NOW) == 1

    # Concurrent selectors may observe the same candidate, but the atomic
    # marker/job claim permits exactly one winner.
    payout_winners = []
    threads = [threading.Thread(
        target=lambda: payout_winners.append(
            store.queue_due_payout_delays(now=NOW, warn_minutes=45)))
        for _ in range(8)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert sum(payout_winners) == 1
    assert store.queue_due_winbacks(now=NOW, discount=5, valid_hours=72) == 1

    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        jobs = conn.execute(
            "SELECT kind,dedupe_key,payload,state FROM bot_notification_jobs ORDER BY id"
        ).fetchall()
        decoded = [(row["kind"], row["dedupe_key"], json.loads(row["payload"]))
                   for row in jobs]
        assert len(decoded) == 8
        assert {(kind, key) for kind, key, _ in decoded} == {
            ("recall", "101"),
            ("montera_customer", "2001"), ("montera_admin", "2001"),
            ("montera_customer", "2002"), ("montera_admin", "2002"),
            ("pay_reminder", "3001"), ("payout_delayed", "4001"),
            ("winback_promo", "5002"),
        }
        assert next(p for k, key, p in decoded
                    if k == "montera_customer" and key == "2001")["has_file"] is True
        assert next(p for k, key, p in decoded
                    if k == "montera_customer" and key == "2002")["has_file"] is False
        assert next(p for k, _, p in decoded if k == "pay_reminder")["session_token"] == "live-latest"
        winback = next(p for k, _, p in decoded if k == "winback_promo")
        assert winback["code"].startswith("BACK5-") and winback["code_id"] > 0
        assert conn.execute(
            "SELECT COUNT(*) FROM promo_codes WHERE code=?", (winback["code"],)
        ).fetchone()[0] == 1

    # Parallel consumers claim every job once.
    claims = []
    lock = threading.Lock()

    def claim_one():
        item = store.claim_notification()
        if item:
            with lock:
                claims.append(item)

    threads = [threading.Thread(target=claim_one) for _ in range(16)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert len(claims) == 8 and len({item["id"] for item in claims}) == 8
    assert store.retry_notification(claims[0]["id"])
    retry = store.claim_notification()
    assert retry["id"] == claims[0]["id"] and retry["attempts"] == 2
    assert store.mark_notification_sent(retry["id"])
    for item in claims[1:]:
        assert store.mark_notification_sent(item["id"])

    # A retrying Montera customer job must not starve its independent admin job.
    assert store.queue_montera(
        order_id=8001, user_id=801, invoice_id="fairness", has_file=False)
    customer = store.claim_notification()
    assert customer["kind"] == "montera_customer"
    assert store.retry_notification(customer["id"])
    admin = store.claim_notification()
    assert admin["kind"] == "montera_admin"
    assert store.mark_notification_sent(admin["id"])
    customer_retry = store.claim_notification()
    assert customer_retry["id"] == customer["id"] and customer_retry["attempts"] == 2
    assert store.mark_notification_sent(customer_retry["id"])

    # Failure on the second Montera job rolls back marker and first job.
    with sqlite3.connect(path) as conn:
        order(conn, 9001, 901, "pending", created=stamp(timedelta(minutes=-5)),
              invoice="fault", deadline=stamp(timedelta(minutes=10)))
        conn.execute("""
            CREATE TRIGGER fail_montera_admin BEFORE INSERT ON bot_notification_jobs
            WHEN NEW.kind='montera_admin' AND NEW.dedupe_key='9001'
            BEGIN SELECT RAISE(ABORT,'montera-final-job-fault'); END
        """)
    try:
        store.queue_due_montera(now=NOW)
        raise AssertionError("fault swallowed")
    except sqlite3.IntegrityError as exc:
        assert "montera-final-job-fault" in str(exc)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sent_notifications WHERE order_id=9001 AND event='receipt_reminder'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM bot_notification_jobs WHERE dedupe_key='9001'"
        ).fetchone() is None
        conn.execute("DROP TRIGGER fail_montera_admin")

    # Winback promo + marker + final job are one transaction.
    with sqlite3.connect(path) as conn:
        order(conn, 9101, 911, "expired", created=stamp(timedelta(hours=-3)),
              updated=stamp(timedelta(hours=-2)))
        conn.execute("""
            CREATE TRIGGER fail_winback_job BEFORE INSERT ON bot_notification_jobs
            WHEN NEW.kind='winback_promo' AND NEW.dedupe_key='9101'
            BEGIN SELECT RAISE(ABORT,'winback-final-job-fault'); END
        """)
    try:
        store.queue_due_winbacks(now=NOW, discount=7, valid_hours=24)
        raise AssertionError("fault swallowed")
    except sqlite3.IntegrityError as exc:
        assert "winback-final-job-fault" in str(exc)
    with sqlite3.connect(path) as conn:
        assert conn.execute(
            "SELECT 1 FROM sent_notifications WHERE order_id=9101 AND event='winback_promo'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM promo_codes WHERE code LIKE 'BACK7-%'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM bot_notification_jobs WHERE dedupe_key='9101'"
        ).fetchone() is None

print("SQLite bot-notification selector/claim/fault checks: OK")
