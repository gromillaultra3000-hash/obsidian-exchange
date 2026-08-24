import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay R3 access/retention writer rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/039_e0_relay_r3_access_retention_writers.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint,status text,rub_amount numeric,updated_at timestamptz)")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,
  recipient_id bigint,payload jsonb,state text,attempts integer,claimed_at timestamptz,updated_at timestamptz)""")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 conn.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text,blocked_at timestamptz DEFAULT now())")
 conn.execute("""CREATE TABLE audit_log(id bigserial PRIMARY KEY,event text NOT NULL,details text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now())""")
 conn.execute("""INSERT INTO audit_log(event,details,created_at) VALUES
  ('old-1','x',now()-interval '91 days'),('old-2','x',now()-interval '100 days'),
  ('boundary-new','x',now()-interval '89 days'),('new','x',now())""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

info=conninfo_to_dict(dsn);info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="5")
relay=make_conninfo(**info)

def call(sql,args=()):
 with psycopg.connect(relay) as conn:return conn.execute(sql,args).fetchone()[0]

with ThreadPoolExecutor(max_workers=12) as pool:
 results=list(pool.map(lambda _:call("SELECT relay_admin_block_user(42,' fraud signal ')"),range(12)))
assert results.count(True)==1 and results.count(False)==11
assert call("SELECT relay_admin_unblock_user(42)") is True
assert call("SELECT relay_admin_unblock_user(42)") is False
assert call("SELECT relay_ops_cleanup_audit()") == 2
assert call("SELECT relay_ops_cleanup_audit()") == 0

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT relay_admin_block_user(0,'x')","SELECT relay_admin_block_user(1,'')",
 "SELECT relay_admin_unblock_user(-1)","SELECT relay_ops_cleanup_audit(1)",
 "SELECT * FROM blocked_users","INSERT INTO blocked_users(user_id,reason) VALUES(5,'raw')",
 "DELETE FROM blocked_users","SELECT * FROM audit_log","DELETE FROM audit_log",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT event FROM audit_log ORDER BY id").fetchall()==[('boundary-new',),('new',)]
 assert conn.execute("SELECT count(*) FROM blocked_users").fetchone()==(0,)
 conn.execute("INSERT INTO blocked_users(user_id,reason) VALUES(99,'keep')")
 conn.execute("""CREATE FUNCTION fail_unblock() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN IF OLD.user_id=99 THEN RAISE EXCEPTION 'injected unblock fault';END IF;RETURN OLD;END $$""")
 conn.execute("CREATE TRIGGER fail_unblock BEFORE DELETE ON blocked_users FOR EACH ROW EXECUTE FUNCTION fail_unblock()")
 conn.execute("INSERT INTO audit_log(event,details,created_at) VALUES('fault-old','x',now()-interval '100 days')")
 conn.execute("""CREATE FUNCTION fail_cleanup() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN IF OLD.event='fault-old' THEN RAISE EXCEPTION 'injected cleanup fault';END IF;RETURN OLD;END $$""")
 conn.execute("CREATE TRIGGER fail_cleanup BEFORE DELETE ON audit_log FOR EACH ROW EXECUTE FUNCTION fail_cleanup()")

for sql in ("SELECT relay_admin_unblock_user(99)","SELECT relay_ops_cleanup_audit()"):
 try:call(sql)
 except psycopg.Error:pass
 else:raise AssertionError("injected R3 fault unexpectedly committed")

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT reason FROM blocked_users WHERE user_id=99").fetchone()==('keep',)
 assert conn.execute("SELECT count(*) FROM audit_log WHERE event='fault-old'").fetchone()==(1,)
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_admin_block_user','relay_admin_unblock_user','relay_ops_cleanup_audit')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()==(0,)

print("E0.3 Relay R3 access/retention writer rehearsal: OK")
