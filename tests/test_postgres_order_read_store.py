import os
import sys
import atexit
import pytest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.order_read_store import PostgresOrderReadStore

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    pytest.skip("TEST_POSTGRES_DSN unset", allow_module_level=True)
s = PostgresOrderReadStore(dsn)
ids = (991101, 991102, 991103)
extra_ids = (991104, 991105)
def cleanup():
    with s._c() as c:
        all_ids = list(ids + extra_ids)
        c.execute("DELETE FROM order_receipts WHERE order_id=ANY(%s)", (all_ids,))
        c.execute("DELETE FROM payment_sessions WHERE order_id=ANY(%s)", (all_ids,))
        c.execute("DELETE FROM orders WHERE order_id=ANY(%s)", (all_ids,))


cleanup()
atexit.register(cleanup)
with s._c() as c:
    c.cursor().executemany(
        "INSERT INTO orders(order_id,user_id,username,currency,rub_amount,crypto_address,status,"
        "created_at,network,agreed_rate,agreed_crypto_amount) VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
        [(ids[0], 9911, "u", "BTC", 1000, "a", "sent", "2026-01-01T00:00:00+00:00", "BTC", 10, .1),
         (ids[1], 9911, "u", "BTC", 2000, "b", "sent", "2026-01-02T00:00:00+00:00", "BTC", 20, .2),
         (ids[2], 9911, "u", "LTC", 3000, "c", "pending", "2026-01-03T00:00:00+00:00", "LTC", None, None)])
    c.execute("INSERT INTO payment_sessions(order_id,session_token,amount,provider,status,created_at) "
              "VALUES(%s,'expired',1,'test','expired','2026-01-02T00:01:00+00:00'),"
              "(%s,'active',1,'test','invoice_created','2026-01-02T00:02:00+00:00')",
              (ids[1], ids[1]))
    c.execute("INSERT INTO order_receipts(order_id,path,filename,content_type) "
              "VALUES(%s,'p','f','image/png')", (ids[1],))
assert s.agreed_quote(ids[1]) == (20.0, .2)
assert s.snapshot(ids[1])["crypto_address"] == "b" and s.snapshot(999999999) is None
assert [r["order_id"] for r in s.customer_orders(9911, limit=2)] == [ids[2], ids[1]]
assert s.customer_orders(9911, limit=2)[1]["session_token"] == "active"
assert [r["order_id"] for r in s.web_customer_orders(9999, 9911, limit=2)] == [ids[2], ids[1]]
assert s.receipt_order_ids(ids) == {ids[1]}
assert [r["order_id"] for r in s.customer_orders(9911, limit=2, offset=1)] == [ids[1], ids[0]]
assert [r["order_id"] for r in s.customer_history(9911)] == list(reversed(ids))
assert s.latest_customer_order_id(9911) == ids[2]
assert s.find_customer(9911)["volume"] == 3000.0
assert s.find_customer("u")["sent_cnt"] >= 2 and s.find_customer("missing-user") is None
recent_ids = [r["order_id"] for r in s.admin_recent(limit=100000)]
assert recent_ids.index(ids[2]) < recent_ids.index(ids[1]) < recent_ids.index(ids[0])
export_ids = [r["order_id"] for r in s.export_recent(limit=100000)]
assert export_ids.index(ids[0]) < export_ids.index(ids[1]) < export_ids.index(ids[2])
agg = s.customer_aggregates(9911)
assert agg == {"total": 3, "completed": 2, "volume": 3000.0,
               "first_at": "2026-01-01T00:00:00+00:00", "favorite_currency": "BTC"}
assert s.provider_success_count(9911) == 2
limits = s.creation_limit_state(
    9911, daily_since="2025-12-31T00:00:00+00:00",
    cooldown_since="2026-01-02T12:00:00+00:00")
assert limits["daily_count"] == 3 and limits["cooldown_active"]
dashboard = s.operator_dashboard(limit=100000)
assert ids[2] in [row["order_id"] for row in dashboard["pending"]]
assert s.pending_usdt_match(sender_address="missing", minimum_rub=1,
                            maximum_rub=9999) is None
assert ids[2] in s.stuck_pending_ids(older_than="2026-02-01T00:00:00+00:00")
with s._c() as c:
    c.execute("INSERT INTO orders(order_id,user_id,username,currency,rub_amount,crypto_address,"
              "status,created_at) VALUES(%s,9911,'u','BTC',4000,'d','paid',now()),"
              "(%s,9912,'v','USDT',50,'sender','pending',now())", extra_ids)
assert s.provider_success_count(9911) == 3
assert extra_ids[0] in [row["order_id"] for row in s.worker_paid_orders(limit=100000)]
assert {9911, 9912}.issubset(set(s.active_customer_ids(days=30)))
assert s.pending_usdt_match(sender_address="sender", minimum_rub=45,
                            maximum_rub=55)["order_id"] == extra_ids[1]
cleanup()
print("PostgreSQL order-read repository checks: OK")
