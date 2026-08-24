import os
from pathlib import Path

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres E4 action proposal: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

import psycopg

ROOT = Path(__file__).resolve().parents[1]
MIGRATION = (ROOT / "deploy/postgres/proposals/025_e4_action_handoff.sql").read_text()
ACL = (ROOT / "deploy/postgres/proposals/025_e4_action_handoff_acl.sql").read_text()


def denied(sql):
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute("SET ROLE obsidian_app")
            conn.execute(sql)
    except psycopg.Error:
        return
    raise AssertionError(f"statement unexpectedly allowed: {sql}")


with psycopg.connect(dsn) as conn:
    for role in ("obsidian_app", "obsidian_readonly", "obsidian_payout"):
        conn.execute(f"CREATE ROLE {role} NOLOGIN")
    conn.execute("CREATE TABLE orders(order_id BIGINT PRIMARY KEY)")
    conn.execute("CREATE TABLE sell_orders(id BIGINT PRIMARY KEY)")
    conn.execute("INSERT INTO orders VALUES(101)")
    conn.execute("INSERT INTO sell_orders VALUES(202)")
    # Simulate the already-applied base runtime ACL for canonical order tables.
    conn.execute("GRANT SELECT ON orders,sell_orders TO obsidian_app")
    conn.execute(MIGRATION)
    conn.execute(ACL)

insert_one = """INSERT INTO e4_action_reservations(
 reservation_id,request_id,draft_id,assessment_id,principal_ref,actor_user_id,
 idempotency_key_sha256,workflow_mapping,payload_sha256,
 quote_expires_at_epoch_ms,requested_at_epoch_ms,expires_at_epoch_ms,state)
 VALUES('r1','r1','d1','a1','p1',7,repeat('1',64),'BUY_ORDER_CREATION',
 repeat('2',64),2000,1000,1500,'reserved')"""
with psycopg.connect(dsn) as conn:
    conn.execute("SET ROLE obsidian_app")
    conn.execute(insert_one)
    conn.execute("UPDATE e4_action_reservations SET state='committed',"
                 "result_kind='BUY_ORDER',result_id=101 WHERE reservation_id='r1'")
    row = conn.execute("SELECT state,result_kind,result_id FROM e4_action_reservations "
                       "WHERE reservation_id='r1'").fetchone()
    assert row == ("committed", "BUY_ORDER", 101)

denied("UPDATE e4_action_reservations SET assessment_id='changed' WHERE reservation_id='r1'")
denied("UPDATE e4_action_reservations SET result_id=101 WHERE reservation_id='r1'")
denied("DELETE FROM e4_action_reservations WHERE reservation_id='r1'")

with psycopg.connect(dsn) as conn:
    conn.execute("SET ROLE obsidian_app")
    conn.execute(insert_one.replace("'r1'", "'r2'").replace("'d1'", "'d2'")
                 .replace("'p1'", "'p2'").replace("repeat('1',64)", "repeat('3',64)"))
try:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET ROLE obsidian_app")
        conn.execute("UPDATE e4_action_reservations SET state='committed',"
                     "result_kind='BUY_ORDER',result_id=999 WHERE reservation_id='r2'")
except psycopg.Error:
    pass
else:
    raise AssertionError("missing BUY result unexpectedly committed")

for role in ("obsidian_readonly", "obsidian_payout"):
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute(f"SET ROLE {role}")
            conn.execute("SELECT * FROM e4_action_reservations")
    except psycopg.Error:
        continue
    raise AssertionError(f"{role} unexpectedly read E4 reservations")

with psycopg.connect(dsn) as conn:
    app = conn.execute("""SELECT
      has_table_privilege('obsidian_app','e4_action_reservations','SELECT'),
      has_table_privilege('obsidian_app','e4_action_reservations','INSERT'),
      has_table_privilege('obsidian_app','e4_action_reservations','DELETE'),
      has_column_privilege('obsidian_app','e4_action_reservations','state','UPDATE'),
      has_column_privilege('obsidian_app','e4_action_reservations','assessment_id','UPDATE')
    """).fetchone()
    assert app == (True, True, False, True, False)
print("PostgreSQL E4 migration/ACL proposal checks: OK")
