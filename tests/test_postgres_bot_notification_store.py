import os
import sys
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.bot_notification_store import PostgresBotNotificationStore


dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres bot notification store: skipped")
    raise SystemExit(0)

store = PostgresBotNotificationStore(dsn)
NOW = datetime(2026, 8, 9, 12, 0, tzinfo=timezone.utc)
ORDER_IDS = [996101, 996201, 996301, 996401, 996501, 996502, 996801, 996901, 996911]
USER_IDS = [99601, 99602, 99603, 99604, 99605, 99609, 99611]
ALL_KEYS = [str(value) for value in ORDER_IDS + USER_IDS]


def cleanup():
    with store._c() as conn:
        conn.execute(
            "DELETE FROM promo_codes WHERE id IN (SELECT (payload->>'code_id')::bigint "
            "FROM bot_notification_jobs WHERE dedupe_key=ANY(%s) AND kind='winback_promo')",
            (ALL_KEYS,),
        )
        conn.execute("DELETE FROM bot_notification_jobs WHERE dedupe_key=ANY(%s)", (ALL_KEYS,))
        conn.execute(
            "DELETE FROM sent_notifications WHERE order_id=ANY(%s)",
            (ORDER_IDS + USER_IDS,),
        )
        conn.execute("DELETE FROM order_receipts WHERE order_id=ANY(%s)", (ORDER_IDS,))
        conn.execute("DELETE FROM payment_sessions WHERE order_id=ANY(%s)", (ORDER_IDS,))
        conn.execute("DELETE FROM blocked_users WHERE user_id=ANY(%s)", (USER_IDS,))
        conn.execute("DELETE FROM orders WHERE order_id=ANY(%s)", (ORDER_IDS,))


def add_order(conn, oid, uid, status, created, *, updated=None, currency="BTC",
              txid=None, invoice=None, deadline=None, receipt_sent=None):
    conn.execute(
        "INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status,"
        "created_at,updated_at,paid_btc_tx,montera_invoice_id,receipt_deadline,receipt_sent_at) "
        "VALUES(%s,%s,%s,2500,'bc1qtest',%s,%s,%s,%s,%s,%s,%s)",
        (oid, uid, currency, status, created, updated, txid, invoice, deadline, receipt_sent),
    )


cleanup()
try:
    with store._c() as conn:
        add_order(conn, 996101, 99601, "sent", NOW - timedelta(days=30))
        add_order(conn, 996201, 99602, "pending", NOW - timedelta(minutes=5),
                  invoice="pg-montera", deadline=NOW + timedelta(minutes=10))
        conn.execute(
            "INSERT INTO order_receipts(order_id,path,filename,content_type,created_at) "
            "VALUES(996201,'/pg','pg.pdf','application/pdf',%s)",
            (NOW - timedelta(minutes=1),),
        )
        add_order(conn, 996301, 99603, "pending", NOW - timedelta(minutes=10))
        conn.execute(
            "INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,created_at,updated_at) "
            "VALUES('pg-live-old',996301,2500,'vertu','awaiting_payment',%s,%s),"
            "('pg-dead-newer',996301,2500,'vertu','failed',%s,%s),"
            "('pg-live-latest',996301,2500,'vertu','invoice_created',%s,%s)",
            (
                NOW - timedelta(minutes=10), NOW - timedelta(minutes=10),
                NOW - timedelta(minutes=9), NOW - timedelta(minutes=9),
                NOW - timedelta(minutes=8), NOW - timedelta(minutes=8),
            ),
        )
        add_order(conn, 996401, 99604, "paid", NOW - timedelta(hours=2),
                  updated=NOW - timedelta(minutes=50), currency="LTC")
        add_order(conn, 996501, 99605, "expired", NOW - timedelta(hours=4),
                  updated=NOW - timedelta(hours=3))
        add_order(conn, 996502, 99605, "expired", NOW - timedelta(hours=3),
                  updated=NOW - timedelta(hours=2))

    assert store.queue_due_recalls(now=NOW) == 1
    assert store.queue_due_montera(now=NOW) == 1
    assert store.queue_due_abandoned(now=NOW) == 1

    winners = []
    threads = [threading.Thread(
        target=lambda: winners.append(
            store.queue_due_payout_delays(now=NOW, warn_minutes=45)))
        for _ in range(8)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert sum(winners) == 1
    assert store.queue_due_winbacks(now=NOW, discount=5, valid_hours=72) == 1

    with store._c() as conn:
        jobs = conn.execute(
            "SELECT kind,dedupe_key,payload FROM bot_notification_jobs "
            "WHERE dedupe_key=ANY(%s) ORDER BY id",
            (ALL_KEYS,),
        ).fetchall()
        assert {(row["kind"], row["dedupe_key"]) for row in jobs} == {
            ("recall", "99601"),
            ("montera_customer", "996201"), ("montera_admin", "996201"),
            ("pay_reminder", "996301"), ("payout_delayed", "996401"),
            ("winback_promo", "996502"),
        }
        montera = next(row for row in jobs if row["kind"] == "montera_customer")
        abandoned = next(row for row in jobs if row["kind"] == "pay_reminder")
        winback = next(row for row in jobs if row["kind"] == "winback_promo")
        assert montera["payload"]["has_file"] is True
        assert abandoned["payload"]["session_token"] == "pg-live-latest"
        assert winback["payload"]["code"].startswith("BACK5-")

    claims = []
    lock = threading.Lock()

    def claim_one():
        item = store.claim_notification()
        if item and item["dedupe_key"] in ALL_KEYS:
            with lock:
                claims.append(item)

    threads = [threading.Thread(target=claim_one) for _ in range(12)]
    [thread.start() for thread in threads]
    [thread.join() for thread in threads]
    assert len(claims) == 6 and len({item["id"] for item in claims}) == 6
    assert store.retry_notification(claims[0]["id"])
    retried = store.claim_notification()
    assert retried["id"] == claims[0]["id"] and retried["attempts"] == 2
    assert store.mark_notification_sent(retried["id"])
    for item in claims[1:]:
        assert store.mark_notification_sent(item["id"])

    # An explicitly retryable customer failure cannot starve the independent
    # admin audience job: unattempted work sorts before attempted work.
    assert store.queue_montera(
        order_id=996801, user_id=99608, invoice_id="pg-fairness", has_file=False)
    customer = store.claim_notification()
    assert customer["kind"] == "montera_customer"
    assert store.retry_notification(customer["id"])
    admin = store.claim_notification()
    assert admin["kind"] == "montera_admin"
    assert store.mark_notification_sent(admin["id"])
    customer_retry = store.claim_notification()
    assert customer_retry["id"] == customer["id"] and customer_retry["attempts"] == 2
    assert store.mark_notification_sent(customer_retry["id"])

    # Failure on the second Montera audience job rolls the first job and marker back.
    with store._c() as conn:
        add_order(conn, 996901, 99609, "pending", NOW - timedelta(minutes=5),
                  invoice="pg-fault", deadline=NOW + timedelta(minutes=10))
        conn.execute("""
            CREATE OR REPLACE FUNCTION bot_notification_montera_fault_test()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.kind='montera_admin' AND NEW.dedupe_key='996901' THEN
                RAISE EXCEPTION 'montera-final-job-fault';
              END IF;
              RETURN NEW;
            END$$
        """)
        conn.execute("""
            CREATE TRIGGER bot_notification_montera_fault_test
            BEFORE INSERT ON bot_notification_jobs FOR EACH ROW
            EXECUTE FUNCTION bot_notification_montera_fault_test()
        """)
    try:
        store.queue_due_montera(now=NOW)
        raise AssertionError("fault swallowed")
    except Exception as exc:
        assert "montera-final-job-fault" in str(exc)
    with store._c() as conn:
        assert conn.execute(
            "SELECT 1 FROM sent_notifications WHERE order_id=996901 AND event='receipt_reminder'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM bot_notification_jobs WHERE dedupe_key='996901'"
        ).fetchone() is None
        conn.execute("DROP TRIGGER bot_notification_montera_fault_test ON bot_notification_jobs")
        conn.execute("DROP FUNCTION bot_notification_montera_fault_test()")

    # The winback promo row also rolls back if the final durable job cannot commit.
    with store._c() as conn:
        add_order(conn, 996911, 99611, "expired", NOW - timedelta(hours=3),
                  updated=NOW - timedelta(hours=2))
        promo_count = conn.execute("SELECT COUNT(*) count FROM promo_codes").fetchone()["count"]
        conn.execute("""
            CREATE OR REPLACE FUNCTION bot_notification_winback_fault_test()
            RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
              IF NEW.kind='winback_promo' AND NEW.dedupe_key='996911' THEN
                RAISE EXCEPTION 'winback-final-job-fault';
              END IF;
              RETURN NEW;
            END$$
        """)
        conn.execute("""
            CREATE TRIGGER bot_notification_winback_fault_test
            BEFORE INSERT ON bot_notification_jobs FOR EACH ROW
            EXECUTE FUNCTION bot_notification_winback_fault_test()
        """)
    try:
        store.queue_due_winbacks(now=NOW, discount=7, valid_hours=24)
        raise AssertionError("fault swallowed")
    except Exception as exc:
        assert "winback-final-job-fault" in str(exc)
    with store._c() as conn:
        assert conn.execute(
            "SELECT 1 FROM sent_notifications WHERE order_id=996911 AND event='winback_promo'"
        ).fetchone() is None
        assert conn.execute(
            "SELECT 1 FROM bot_notification_jobs WHERE dedupe_key='996911'"
        ).fetchone() is None
        assert conn.execute("SELECT COUNT(*) count FROM promo_codes").fetchone()["count"] == promo_count
        conn.execute("DROP TRIGGER bot_notification_winback_fault_test ON bot_notification_jobs")
        conn.execute("DROP FUNCTION bot_notification_winback_fault_test()")
finally:
    # Drop fault hooks even if an assertion interrupted their normal cleanup.
    with store._c() as conn:
        conn.execute("DROP TRIGGER IF EXISTS bot_notification_montera_fault_test ON bot_notification_jobs")
        conn.execute("DROP FUNCTION IF EXISTS bot_notification_montera_fault_test()")
        conn.execute("DROP TRIGGER IF EXISTS bot_notification_winback_fault_test ON bot_notification_jobs")
        conn.execute("DROP FUNCTION IF EXISTS bot_notification_winback_fault_test()")
    cleanup()

print("PostgreSQL bot-notification selector/claim/fault checks: OK")
