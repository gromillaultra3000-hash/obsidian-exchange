import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 notifier ACL rehearsal: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

import psycopg

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = (ROOT / "deploy/postgres/proposals/026_e0_notifier_functions.sql").read_text()


def denied(statement, params=()):
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute("SET ROLE obsidian_notifier")
            conn.execute(statement, params)
    except psycopg.Error:
        return
    raise AssertionError(f"statement unexpectedly allowed: {statement}")


with psycopg.connect(dsn) as conn:
    conn.execute("CREATE TABLE orders(order_id bigserial primary key,user_id bigint not null,rub_amount numeric not null,currency text not null,paid_btc_tx text,status text not null)")
    conn.execute("CREATE TABLE sent_notifications(order_id bigint,event text,primary key(order_id,event))")
    conn.execute("CREATE TABLE gift_vouchers(id bigserial primary key,order_id bigint,status text not null)")
    conn.execute("CREATE TABLE reviews(id bigserial primary key,order_id bigint unique,user_id bigint,status text not null)")
    conn.execute("INSERT INTO orders(user_id,rub_amount,currency,status) VALUES(7,100,'BTC','paid'),(8,200,'LTC','sent'),(9,300,'BTC','pending'),(10,400,'BTC','paid'),(11,500,'LTC','sent'),(12,600,'BTC','paid'),(13,700,'LTC','sent')")
    conn.execute("INSERT INTO gift_vouchers(order_id,status) VALUES(1,'pending'),(4,'pending'),(6,'pending')")
    conn.execute(PROPOSAL)

with psycopg.connect(dsn) as conn:
    conn.execute("SET ROLE obsidian_notifier")
    assert conn.execute("SELECT order_id,user_id FROM notifier_pending('paid',1)").fetchall() == [(1,7)]
    assert conn.execute("SELECT notifier_complete(1,'paid')").fetchone()[0] is True
    assert conn.execute("SELECT notifier_complete(1,'paid')").fetchone()[0] is False
    assert conn.execute("SELECT notifier_ensure_review(2,8)").fetchone()[0] is True
    assert conn.execute("SELECT notifier_ensure_review(2,8)").fetchone()[0] is False

for statement in (
    "SELECT * FROM orders", "INSERT INTO sent_notifications VALUES(2,'sent')",
    "UPDATE gift_vouchers SET status='paid'", "SELECT nextval('reviews_id_seq')",
    "CREATE TABLE forbidden(id bigint)", "CREATE TEMP TABLE forbidden_temp(id bigint)",
    "TRUNCATE reviews", "ALTER ROLE obsidian_notifier CREATEDB",
):
    denied(statement)

for statement, params in (
    ("SELECT * FROM notifier_pending(%s,10)", ("payout_triggered",)),
    ("SELECT * FROM notifier_pending('paid',%s)", (0,)),
    ("SELECT * FROM notifier_pending('paid',%s)", (101,)),
    ("SELECT notifier_complete(3,'paid')", ()),
    ("SELECT notifier_complete(0,'paid')", ()),
    ("SELECT notifier_ensure_review(2,999)", ()),
    ("SELECT notifier_ensure_review(1,7)", ()),
    ("SELECT notifier_ensure_review(2,0)", ()),
):
    denied(statement, params)


def concurrent_call(statement, workers=12):
    barrier = Barrier(workers)

    def invoke(_):
        with psycopg.connect(dsn) as conn:
            conn.execute("SET ROLE obsidian_notifier")
            barrier.wait()
            return conn.execute(statement).fetchone()[0]

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(invoke, range(workers)))


complete_results = concurrent_call("SELECT notifier_complete(4,'paid')")
assert complete_results.count(True) == 1
assert complete_results.count(False) == 11

review_results = concurrent_call("SELECT notifier_ensure_review(5,11)")
assert review_results.count(True) == 1
assert review_results.count(False) == 11


with psycopg.connect(dsn) as conn:
    conn.execute("CREATE SCHEMA fixture_fault")
    conn.execute("""CREATE FUNCTION fixture_fault.synthetic_gift_update_fault() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.order_id=6 THEN RAISE EXCEPTION 'synthetic_gift_update_fault'; END IF;
        RETURN NEW;
      END $$""")
    conn.execute("REVOKE ALL ON FUNCTION fixture_fault.synthetic_gift_update_fault() FROM PUBLIC")
    conn.execute("GRANT USAGE ON SCHEMA fixture_fault TO obsidian_notifier_owner")
    conn.execute("GRANT EXECUTE ON FUNCTION fixture_fault.synthetic_gift_update_fault() TO obsidian_notifier_owner")
    conn.execute("""CREATE TRIGGER synthetic_gift_update_fault
      BEFORE UPDATE ON gift_vouchers FOR EACH ROW
      EXECUTE FUNCTION fixture_fault.synthetic_gift_update_fault()""")

try:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_notifier")
        conn.execute("SELECT notifier_complete(6,'paid')")
except psycopg.Error as exc:
    assert "synthetic_gift_update_fault" in str(exc)
else:
    raise AssertionError("injected mid-function fault unexpectedly committed")


def caller_rollback(statement):
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute("SET ROLE obsidian_notifier")
            assert conn.execute(statement).fetchone()[0] is True
            raise RuntimeError("synthetic_fault_before_commit")
    except RuntimeError as exc:
        assert str(exc) == "synthetic_fault_before_commit"


caller_rollback("SELECT notifier_ensure_review(7,13)")

with psycopg.connect(dsn) as conn:
    assert conn.execute("SELECT status FROM gift_vouchers WHERE order_id=1").fetchone()[0] == "paid"
    assert conn.execute("SELECT status FROM gift_vouchers WHERE order_id=4").fetchone()[0] == "paid"
    assert conn.execute("SELECT count(*) FROM sent_notifications WHERE order_id=4 AND event='paid'").fetchone()[0] == 1
    assert conn.execute("SELECT count(*) FROM reviews WHERE order_id=5 AND user_id=11 AND status='pending_rating'").fetchone()[0] == 1
    assert conn.execute("SELECT status FROM gift_vouchers WHERE order_id=6").fetchone()[0] == "pending"
    assert conn.execute("SELECT count(*) FROM sent_notifications WHERE order_id=6").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM reviews WHERE order_id=7").fetchone()[0] == 0
    acl = conn.execute("""SELECT
      has_table_privilege('obsidian_notifier','orders','SELECT'),
      has_table_privilege('obsidian_notifier','reviews','INSERT'),
      has_sequence_privilege('obsidian_notifier','reviews_id_seq','USAGE'),
      has_function_privilege('obsidian_notifier','notifier_pending(text,integer)','EXECUTE'),
      has_function_privilege('obsidian_notifier','notifier_complete(bigint,text)','EXECUTE'),
      has_function_privilege('obsidian_notifier','notifier_ensure_review(bigint,bigint)','EXECUTE')
    """).fetchone()
    assert acl == (False,False,False,True,True,True)
    assert conn.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace WHERE n.nspname='public' AND has_function_privilege('obsidian_notifier',p.oid,'EXECUTE')").fetchone()[0] == 3

print("E0.3 notifier ACL, concurrency, rollback and adversarial denial rehearsal: OK")
