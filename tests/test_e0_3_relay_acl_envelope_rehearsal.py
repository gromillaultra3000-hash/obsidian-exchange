import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier


dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 Relay ACL envelope rehearsal: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo


ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = (ROOT / "deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()


with psycopg.connect(dsn) as conn:
    conn.execute("""CREATE TABLE orders(
      order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,status text NOT NULL,
      rub_amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())""")
    conn.execute("""CREATE TABLE payment_notification_outbox(
      id bigserial PRIMARY KEY,order_id bigint NOT NULL,recipient_id bigint NOT NULL,
      payload jsonb NOT NULL,state text NOT NULL DEFAULT 'pending',attempts integer NOT NULL DEFAULT 0,
      claimed_at timestamptz,updated_at timestamptz NOT NULL DEFAULT now())""")
    conn.execute("""CREATE TABLE support_tickets(
      ticket_id bigserial PRIMARY KEY,web_user_id bigint NOT NULL,subject text NOT NULL,status text NOT NULL)""")
    conn.execute("""CREATE TABLE payment_transition_audit(
      id bigserial PRIMARY KEY,order_id bigint NOT NULL,from_status text NOT NULL,
      to_status text NOT NULL,evidence text NOT NULL)""")
    conn.execute("""INSERT INTO orders(user_id,status,rub_amount) VALUES
      (7,'paid',100),(7,'pending',200),(8,'pending',300),(9,'pending',400)""")
    conn.execute("""INSERT INTO payment_notification_outbox(order_id,recipient_id,payload)
      VALUES(1,7,'{"order_id":1}')""")
    conn.execute(PROPOSAL)


relay_dsn = conninfo_to_dict(dsn)
relay_dsn.update(user="obsidian_relay", password="synthetic-rehearsal-only", connect_timeout="2")
relay_dsn = make_conninfo(**relay_dsn)


def denied(statement, params=()):
    try:
        with psycopg.connect(relay_dsn) as conn:
            conn.execute(statement, params)
    except psycopg.Error:
        return
    raise AssertionError(f"statement unexpectedly allowed: {statement}")


with psycopg.connect(relay_dsn) as conn:
    assert conn.execute("SHOW statement_timeout").fetchone()[0] == "5s"
    assert conn.execute("SHOW lock_timeout").fetchone()[0] == "1s"
    assert conn.execute("SELECT * FROM relay_rehearsal_public_stats()").fetchone() == (4,1,100)
    assert conn.execute(
        "SELECT * FROM relay_rehearsal_customer_orders(%s,%s)",(7,10)
    ).fetchall() == [(2,"pending",200),(1,"paid",100)]
    assert conn.execute("SELECT relay_rehearsal_support_create(7,' Help ') ").fetchone()[0] == 1


for statement in (
    "SELECT * FROM orders",
    "UPDATE orders SET status='paid'",
    "INSERT INTO support_tickets(web_user_id,subject,status) VALUES(1,'x','open')",
    "SELECT nextval('support_tickets_ticket_id_seq')",
    "CREATE TABLE forbidden(id bigint)",
    "CREATE TEMP TABLE forbidden_temp(id bigint)",
    "ALTER ROLE obsidian_relay CREATEDB",
):
    denied(statement)

for statement, params in (
    ("SELECT * FROM relay_rehearsal_customer_orders(%s,10)",(0,)),
    ("SELECT * FROM relay_rehearsal_customer_orders(7,%s)",(0,)),
    ("SELECT * FROM relay_rehearsal_customer_orders(7,%s)",(101,)),
    ("SELECT relay_rehearsal_support_create(7,%s)",("x"*201,)),
    ("SELECT relay_rehearsal_mark_paid(2,%s)",("x"*161,)),
):
    denied(statement,params)


def concurrent(statement, workers=12):
    barrier = Barrier(workers)

    def invoke(_):
        with psycopg.connect(relay_dsn) as conn:
            barrier.wait()
            row = conn.execute(statement).fetchone()
            return row[0] if row else None

    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(invoke,range(workers)))


claims = concurrent("SELECT id FROM relay_rehearsal_claim_notification()")
assert claims.count(1) == 1 and claims.count(None) == 11
payments = concurrent("SELECT relay_rehearsal_mark_paid(2,'verified-provider')")
assert payments.count("transitioned") == 1
assert payments.count("already_paid") == 11


with psycopg.connect(dsn) as conn:
    conn.execute("CREATE SCHEMA fixture_fault")
    conn.execute("""CREATE FUNCTION fixture_fault.reject_order_four() RETURNS trigger
      LANGUAGE plpgsql AS $$ BEGIN
        IF NEW.order_id=4 THEN RAISE EXCEPTION 'synthetic_payment_audit_fault'; END IF;
        RETURN NEW;
      END $$""")
    conn.execute("""CREATE TRIGGER synthetic_payment_audit_fault BEFORE INSERT
      ON payment_transition_audit FOR EACH ROW EXECUTE FUNCTION fixture_fault.reject_order_four()""")

try:
    with psycopg.connect(relay_dsn) as conn:
        conn.execute("SELECT relay_rehearsal_mark_paid(4,'verified-provider')")
except psycopg.Error as exc:
    assert "synthetic_payment_audit_fault" in str(exc)
else:
    raise AssertionError("injected transition fault unexpectedly committed")

try:
    with psycopg.connect(relay_dsn) as conn:
        assert conn.execute("SELECT relay_rehearsal_support_create(8,'rollback')").fetchone()[0] == 2
        raise RuntimeError("synthetic_fault_before_commit")
except RuntimeError as exc:
    assert str(exc) == "synthetic_fault_before_commit"


held=[]
try:
    for _ in range(12):
        held.append(psycopg.connect(relay_dsn))
    try:
        psycopg.connect(relay_dsn)
    except psycopg.Error as exc:
        assert "too many connections" in str(exc).lower()
    else:
        raise AssertionError("thirteenth Relay connection unexpectedly succeeded")
finally:
    for conn in held:
        conn.close()


with psycopg.connect(dsn) as conn:
    role = conn.execute("""SELECT rolcanlogin,rolconnlimit,rolsuper,rolcreatedb,
      rolcreaterole,rolinherit,rolreplication,rolbypassrls FROM pg_roles
      WHERE rolname='obsidian_relay'""").fetchone()
    assert role == (True,12,False,False,False,False,False,False)
    owner = conn.execute("""SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,
      rolinherit,rolreplication,rolbypassrls FROM pg_roles
      WHERE rolname='obsidian_relay_owner'""").fetchone()
    assert owner == (False,False,False,False,False,False,False)
    assert conn.execute("""SELECT count(*) FROM pg_auth_members WHERE
      roleid IN (SELECT oid FROM pg_roles WHERE rolname IN ('obsidian_relay','obsidian_relay_owner'))
      OR member IN (SELECT oid FROM pg_roles WHERE rolname IN ('obsidian_relay','obsidian_relay_owner'))""").fetchone()[0] == 0
    acl = conn.execute("""SELECT
      has_database_privilege('obsidian_relay',current_database(),'CONNECT'),
      has_database_privilege('obsidian_relay',current_database(),'TEMPORARY'),
      has_schema_privilege('obsidian_relay','public','USAGE'),
      has_schema_privilege('obsidian_relay','public','CREATE'),
      has_table_privilege('obsidian_relay','orders','SELECT'),
      has_table_privilege('obsidian_relay_owner','orders','SELECT'),
      has_column_privilege('obsidian_relay_owner','orders','status','SELECT'),
      has_sequence_privilege('obsidian_relay','support_tickets_ticket_id_seq','USAGE')""").fetchone()
    assert acl == (True,False,True,False,False,False,True,False)
    assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
      WHERE n.nspname='public' AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0] == 5
    assert conn.execute("SELECT status FROM orders WHERE order_id=4").fetchone()[0] == "pending"
    assert conn.execute("SELECT count(*) FROM payment_transition_audit WHERE order_id=4").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM support_tickets WHERE subject='rollback'").fetchone()[0] == 0

print("E0.3 Relay ACL envelope, limit, concurrency, rollback and denial rehearsal: OK")
