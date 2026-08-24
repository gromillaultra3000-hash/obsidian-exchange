import json, sqlite3, sys, tempfile
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"relay"))
from repositories.payment_transition_store import SQLitePaymentTransitionStore

with tempfile.TemporaryDirectory() as td:
    path=str(Path(td)/"payment.db")
    with sqlite3.connect(path) as conn:
        conn.executescript("""
        CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,updated_at TEXT);
        CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,session_token TEXT UNIQUE,order_id INTEGER,
          provider TEXT,status TEXT,updated_at TEXT);
        CREATE TABLE gift_vouchers(id INTEGER PRIMARY KEY,order_id INTEGER,status TEXT);
        CREATE TABLE payment_transition_audit(id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id INTEGER NOT NULL,provider TEXT NOT NULL,action TEXT NOT NULL,
          from_status TEXT,to_status TEXT,evidence TEXT NOT NULL,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        CREATE TABLE payment_notification_outbox(id INTEGER PRIMARY KEY AUTOINCREMENT,
          order_id INTEGER NOT NULL UNIQUE,recipient_id INTEGER NOT NULL,payload TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'pending',attempts INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,claimed_at TEXT,sent_at TEXT,
          updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
        INSERT INTO orders VALUES(1,22,'pending',NULL),(2,23,'expired',NULL),(3,-3,'pending',NULL),
          (4,24,'pending',NULL);
        INSERT INTO payment_sessions VALUES(1,'live',1,'vertu','invoice_created',NULL);
        INSERT INTO payment_sessions VALUES(2,'old',1,'vertu','failed',NULL);
        INSERT INTO gift_vouchers VALUES(1,1,'pending');
        """)
    store=SQLitePaymentTransitionStore(path)
    with sqlite3.connect(path) as conn:
        conn.execute("CREATE TRIGGER fail_payment_outbox BEFORE INSERT ON payment_notification_outbox "
                     "WHEN NEW.order_id=4 BEGIN SELECT RAISE(ABORT,'fault'); END")
    try:
        store.mark_paid(4,provider="lava",evidence="fault")
        raise AssertionError("outbox fault did not abort transition")
    except sqlite3.IntegrityError:
        pass
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM orders WHERE order_id=4").fetchone()[0]=="pending"
        assert conn.execute("SELECT count(*) FROM payment_transition_audit WHERE order_id=4").fetchone()[0]==0
    result=store.mark_paid(1,provider="vertu",evidence="poll:invoice",session_token="live")
    assert result["action"]=="transitioned"
    assert store.mark_paid(1,provider="vertu",evidence="retry")["action"]=="already_paid"
    assert store.mark_paid(2,provider="lava",evidence="callback")["action"]=="status_conflict"
    assert store.mark_paid(99,provider="lava",evidence="callback")["action"]=="missing"
    assert store.mark_paid(3,provider="lava",evidence="callback")["action"]=="transitioned"
    with sqlite3.connect(path) as conn:
        assert conn.execute("SELECT status FROM payment_sessions WHERE session_token='live'").fetchone()[0]=="paid"
        assert conn.execute("SELECT status FROM payment_sessions WHERE session_token='old'").fetchone()[0]=="failed"
        assert conn.execute("SELECT status FROM gift_vouchers WHERE id=1").fetchone()[0]=="paid"
        assert conn.execute("SELECT count(*) FROM payment_transition_audit").fetchone()[0]==2
        assert conn.execute("SELECT count(*) FROM payment_notification_outbox").fetchone()[0]==1
    item=store.claim_notification(); assert json.loads(item["payload"])["order_id"]==1
    assert store.retry_notification(item["id"])
    item=store.claim_notification(); assert item["attempts"]==2
    assert store.mark_notification_sent(item["id"])
    assert store.claim_notification() is None
print("SQLite payment transition repository checks: OK")
