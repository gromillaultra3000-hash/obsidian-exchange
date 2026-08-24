import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"relay"))
from repositories.order_workflow_store import SQLiteOrderWorkflowStore


def seed(path):
    with sqlite3.connect(path) as c:
        c.executescript("""
        CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,currency TEXT,
          rub_amount REAL,status TEXT,paid_btc_tx TEXT,updated_at TEXT,
          verification_requested TEXT,montera_invoice_id TEXT,receipt_deadline TEXT);
        CREATE TABLE sent_notifications(order_id INTEGER,event TEXT,
          PRIMARY KEY(order_id,event));
        """)
        c.executemany("INSERT INTO orders(order_id,user_id,currency,rub_amount,status) VALUES(?,?,?,?,?)",
          [(1,7,'BTC',1000,'pending'),(2,7,'BTC',1000,'expired'),
           (3,7,'BTC',1000,'pending'),(4,7,'BTC',1000,'paid'),
           (5,7,'BTC',1000,'pending'),(6,8,'BTC',1000,'pending')])


with tempfile.TemporaryDirectory() as td:
    path=str(Path(td)/"workflow.db"); seed(path); s=SQLiteOrderWorkflowStore(path)
    assert not s.cancel_pending_for_owner(1,8)
    wins=[]
    threads=[threading.Thread(target=lambda: wins.append(s.cancel_pending_for_owner(1,7))) for _ in range(8)]
    [t.start() for t in threads]; [t.join() for t in threads]
    assert sum(wins)==1
    assert s.reopen_review(2) and not s.reopen_review(2)
    assert s.reject_review(3) and not s.reject_review(3)
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT event FROM sent_notifications WHERE order_id=3").fetchone()==('receipt_rejected',)
    tx="a"*64
    assert s.mark_sent(4,"not-a-tx")["action"]=="invalid_txid"
    assert s.mark_sent(4,tx)=={"action":"transitioned","order_id":4,"txid":tx}
    assert s.mark_sent(4,"b"*64)["action"]=="status_conflict"
    assert s.request_verification(5,"video")["action"]=="requested"
    assert s.request_verification(5,"pdf-success")["action"]=="conflict"
    assert not s.clear_verification(5,"pdf-success") and s.clear_verification(5,"video")
    assert s.retry_amount_for_owner(5,7,"2500.50")
    assert not s.retry_amount_for_owner(6,7,3000)
    assert s.set_montera_invoice(5,"deal-1","2026-01-01 00:30:00")
    assert not s.set_montera_invoice(5,"deal-2","2026-01-01 00:30:00")
    for bad in (0,-1,"nan"):
        try: s.retry_amount_for_owner(5,7,bad); raise AssertionError("bad amount accepted")
        except ValueError: pass

    # The reject marker is part of the same transaction as the state change.
    with sqlite3.connect(path) as c:
        c.execute("INSERT INTO orders(order_id,user_id,currency,rub_amount,status) VALUES(9,7,'BTC',1,'pending')")
        c.execute("CREATE TRIGGER fail_marker BEFORE INSERT ON sent_notifications "
                  "WHEN NEW.order_id=9 BEGIN SELECT RAISE(ABORT,'fault'); END")
    try: s.reject_review(9); raise AssertionError("fault was swallowed")
    except sqlite3.IntegrityError: pass
    with sqlite3.connect(path) as c:
        assert c.execute("SELECT status FROM orders WHERE order_id=9").fetchone()==('pending',)
print("SQLite order-workflow repository checks: OK")
