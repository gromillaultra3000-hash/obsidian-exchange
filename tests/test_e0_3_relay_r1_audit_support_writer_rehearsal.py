import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay R1 audit/support writer rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/037_e0_relay_r1_audit_support_writers.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint,status text,
  rub_amount numeric(20,2),updated_at timestamptz DEFAULT now())""")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,
  recipient_id bigint,payload jsonb,state text,attempts integer,claimed_at timestamptz,updated_at timestamptz)""")
 conn.execute("""CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,
  from_status text,to_status text,evidence text)""")
 conn.execute("""CREATE TABLE support_tickets(id bigserial PRIMARY KEY,
  ticket_id bigint GENERATED ALWAYS AS (id) STORED UNIQUE,web_user_id bigint NOT NULL DEFAULT 0,
  user_id bigint,username text,subject text NOT NULL,status text NOT NULL DEFAULT 'open',
  created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now())""")
 conn.execute("CREATE SEQUENCE support_tickets_ticket_id_seq")
 conn.execute("""CREATE TABLE support_messages(id bigserial PRIMARY KEY,ticket_id bigint NOT NULL,
  sender text NOT NULL,message text NOT NULL,created_at timestamptz NOT NULL DEFAULT now())""")
 conn.execute("""CREATE TABLE audit_log(id bigserial PRIMARY KEY,event text NOT NULL,
  details text NOT NULL,created_at timestamptz NOT NULL DEFAULT now())""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

info=conninfo_to_dict(dsn)
info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="5")
relay=make_conninfo(**info)

def call(sql,args=()):
 with psycopg.connect(relay) as conn:return conn.execute(sql,args).fetchone()

with ThreadPoolExecutor(max_workers=12) as pool:
 list(pool.map(lambda n:call("SELECT relay_ops_audit(%s,%s)",(f"event-{n}",f"detail-{n}")),range(12)))

with psycopg.connect(relay) as conn:
 telegram_id=conn.execute(
  "SELECT relay_support_create(' Telegram ','first',77,'user77',0)").fetchone()[0]
 web_id=conn.execute(
  "SELECT relay_support_create(' Web ','first',NULL,NULL,88)").fetchone()[0]
 assert conn.execute(
  "SELECT * FROM relay_support_user_reply(%s,77,0,'telegram reply')",(telegram_id,)).fetchone()==('Telegram','user77')
 assert conn.execute(
  "SELECT * FROM relay_support_user_reply(%s,NULL,88,'web reply')",(web_id,)).fetchone()==('Web',None)
 assert conn.execute(
  "SELECT * FROM relay_support_user_reply(%s,78,0,'foreign')",(telegram_id,)).fetchall()==[]
 assert conn.execute(
  "SELECT * FROM relay_support_user_reply(%s,NULL,89,'foreign')",(web_id,)).fetchall()==[]

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT relay_ops_audit('', 'x')",
 "SELECT relay_support_create('', 'x', 1, NULL, 0)",
 "SELECT relay_support_create('x', 'x', 1, NULL, 2)",
 "SELECT * FROM relay_support_user_reply(1,1,2,'x')",
 "SELECT * FROM audit_log","INSERT INTO audit_log(event,details) VALUES('raw','raw')",
 "SELECT * FROM support_tickets","INSERT INTO support_messages(ticket_id,sender,message) VALUES(1,'user','raw')",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT count(*) FROM audit_log").fetchone()==(12,)
 assert conn.execute("SELECT count(*) FROM support_tickets").fetchone()==(2,)
 assert conn.execute("SELECT count(*) FROM support_messages").fetchone()==(4,)
 assert conn.execute("SELECT count(*) FROM support_messages WHERE sender<>'user'").fetchone()==(0,)
 conn.execute("UPDATE support_tickets SET status='closed' WHERE id=%s",(web_id,))
 conn.execute("""CREATE FUNCTION fail_support_message() RETURNS trigger LANGUAGE plpgsql AS $$
  BEGIN IF NEW.message='fault' THEN RAISE EXCEPTION 'injected support fault';END IF;RETURN NEW;END $$""")
 conn.execute("CREATE TRIGGER fail_support BEFORE INSERT ON support_messages FOR EACH ROW EXECUTE FUNCTION fail_support_message()")

for sql in (
 "SELECT relay_support_create('fault ticket','fault',99,NULL,0)",
 f"SELECT * FROM relay_support_user_reply({web_id},NULL,88,'fault')",
):
 try:
  with psycopg.connect(relay) as conn:conn.execute(sql)
 except psycopg.Error:pass
 else:raise AssertionError("injected support fault unexpectedly committed")

with psycopg.connect(dsn) as conn:
 assert conn.execute("SELECT count(*) FROM support_tickets").fetchone()==(2,)
 assert conn.execute("SELECT status FROM support_tickets WHERE id=%s",(web_id,)).fetchone()==('closed',)
 assert conn.execute("SELECT count(*) FROM support_messages").fetchone()==(4,)
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_ops_audit','relay_support_create','relay_support_user_reply')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()==(0,)

print("E0.3 Relay R1 audit/support writer rehearsal: OK")
