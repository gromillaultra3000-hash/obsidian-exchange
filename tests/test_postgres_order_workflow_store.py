import os
import sys
import threading
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"relay"))
from repositories.order_workflow_store import PostgresOrderWorkflowStore

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres order workflow store: skipped"); raise SystemExit(0)
s=PostgresOrderWorkflowStore(dsn); ids=list(range(992101,992110))
with s._c() as c:
    c.execute("DELETE FROM sent_notifications WHERE order_id=ANY(%s)",(ids,))
    c.execute("DELETE FROM orders WHERE order_id=ANY(%s)",(ids,))
    c.cursor().executemany(
      "INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status) VALUES(%s,%s,%s,%s,'a',%s)",
      [(ids[0],7,'BTC',1000,'pending'),(ids[1],7,'BTC',1000,'expired'),
       (ids[2],7,'BTC',1000,'pending'),(ids[3],7,'BTC',1000,'paid'),
       (ids[4],7,'BTC',1000,'pending'),(ids[5],8,'BTC',1000,'pending')])
assert not s.cancel_pending_for_owner(ids[0],8)
wins=[]; threads=[threading.Thread(target=lambda:wins.append(s.cancel_pending_for_owner(ids[0],7))) for _ in range(8)]
[t.start() for t in threads]; [t.join() for t in threads]; assert sum(wins)==1
assert s.reopen_review(ids[1]) and not s.reopen_review(ids[1])
assert s.reject_review(ids[2]) and not s.reject_review(ids[2])
tx="a"*64
assert s.mark_sent(ids[3],"bad")["action"]=="invalid_txid"
assert s.mark_sent(ids[3],tx)["action"]=="transitioned"
assert s.mark_sent(ids[3],"b"*64)["action"]=="status_conflict"
assert s.request_verification(ids[4],"video")["action"]=="requested"
assert s.request_verification(ids[4],"pdf-success")["action"]=="conflict"
assert not s.clear_verification(ids[4],"pdf-success") and s.clear_verification(ids[4],"video")
assert s.retry_amount_for_owner(ids[4],7,"2500.50") and not s.retry_amount_for_owner(ids[5],7,3000)
assert s.set_montera_invoice(ids[4],"deal-1","2026-01-01T00:30:00+00:00")
assert not s.set_montera_invoice(ids[4],"deal-2","2026-01-01T00:30:00+00:00")
with s._c() as c:
    assert c.execute("SELECT COUNT(*) FROM sent_notifications WHERE order_id=%s AND event='receipt_rejected'",
                     (ids[2],)).fetchone()[0]==1
    c.execute("DELETE FROM sent_notifications WHERE order_id=ANY(%s)",(ids,))
    c.execute("DELETE FROM orders WHERE order_id=ANY(%s)",(ids,))
print("PostgreSQL order-workflow repository checks: OK")
