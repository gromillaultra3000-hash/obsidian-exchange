import os
import sys
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres E4 action handoff store: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

import psycopg
from repositories.e4_action_handoff_store import PostgresE4ActionHandoffStore
from test_e4_action_handoff_store import build


def reset_schema():
    with psycopg.connect(dsn) as conn:
        conn.execute("DROP TABLE IF EXISTS e4_action_reservations,orders,sell_orders CASCADE")
        conn.execute((ROOT / "tests/e4_action_reservation_rehearsal.sql").read_text())
        conn.execute("""CREATE TABLE orders(
          order_id BIGSERIAL PRIMARY KEY,user_id BIGINT,username TEXT,currency TEXT,
          rub_amount NUMERIC,crypto_address TEXT,status TEXT,web_user_id BIGINT,
          network TEXT,agreed_rate NUMERIC,agreed_crypto_amount NUMERIC,
          agreed_at TIMESTAMPTZ)""")
        conn.execute("""CREATE TABLE sell_orders(
          id BIGSERIAL PRIMARY KEY,user_id BIGINT,currency TEXT,crypto_amount NUMERIC,
          rub_amount NUMERIC,sbp_phone TEXT,receive_address TEXT,status TEXT,
          payout_method TEXT,payout_bank TEXT,payout_details TEXT,payout_name TEXT)""")


reset_schema()
args = build("BUY_CRYPTO")
barrier, results, errors = threading.Barrier(2), [], []
def worker():
    try:
        barrier.wait()
        results.append(PostgresE4ActionHandoffStore(dsn).handoff(**args))
    except Exception as exc:
        errors.append(exc)
threads = [threading.Thread(target=worker) for _ in range(2)]
for thread in threads: thread.start()
for thread in threads: thread.join()
assert errors == []
assert sorted(item["action"] for item in results) == ["created", "replayed"]
assert PostgresE4ActionHandoffStore(dsn).handoff(**args)["action"] == "replayed"
with psycopg.connect(dsn) as conn:
    assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 1
    assert conn.execute("SELECT state,result_kind,result_id FROM "
                        "e4_action_reservations").fetchone() == ("committed", "BUY_ORDER", 1)

reset_schema()
sell = build("SELL_CRYPTO")
created = PostgresE4ActionHandoffStore(dsn).handoff(**sell)
assert created == {"action": "created", "result_kind": "SELL_ORDER", "result_id": 1}
assert PostgresE4ActionHandoffStore(dsn).handoff(**sell)["action"] == "replayed"

reset_schema()
def fail(): raise RuntimeError("injected")
try:
    PostgresE4ActionHandoffStore(dsn, fault_after_order=fail).handoff(**build())
    raise AssertionError("fault injection did not fail")
except RuntimeError as exc:
    assert str(exc) == "injected"
with psycopg.connect(dsn) as conn:
    assert conn.execute("SELECT count(*) FROM orders").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM e4_action_reservations").fetchone()[0] == 0
    conn.execute("DROP TABLE e4_action_reservations,orders,sell_orders")
print("PostgreSQL E4 atomic action handoff checks: OK")
