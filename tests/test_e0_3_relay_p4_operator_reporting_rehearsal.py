import os
from pathlib import Path

dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
 print("E0.3 Relay P4 operator reporting rehearsal: skipped (TEST_POSTGRES_DSN unset)")
 raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo

ROOT=Path(__file__).resolve().parents[1]
ENVELOPE=(ROOT/"deploy/postgres/proposals/028_e0_relay_acl_envelope.sql").read_text()
PACKAGE=(ROOT/"deploy/postgres/proposals/034_e0_relay_p4_operator_reporting_bodies.sql").read_text()

with psycopg.connect(dsn) as conn:
 conn.execute("""CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint NOT NULL,
  username text,currency text NOT NULL,rub_amount numeric(20,2) NOT NULL,status text NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz)""")
 conn.execute("""CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,order_id bigint,
  provider text)""")
 conn.execute("""CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text,
  blocked_at timestamptz NOT NULL DEFAULT now())""")
 conn.execute("""CREATE TABLE provider_health(provider text PRIMARY KEY,is_healthy boolean,
  failed_count integer,avg_response_time double precision,status text,blocker text)""")
 conn.execute("""CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,
  recipient_id bigint,payload jsonb,state text,attempts integer DEFAULT 0,claimed_at timestamptz,
  updated_at timestamptz DEFAULT now())""")
 conn.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 conn.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)")
 conn.execute("""INSERT INTO orders(order_id,user_id,username,currency,rub_amount,status,created_at)
  SELECT g,g,'user-'||g,'C'||lpad((g%40)::text,2,'0'),g,
   CASE WHEN g%3=0 THEN 'sent' WHEN g%3=1 THEN 'pending' ELSE 'status-'||(g%40) END,
   timestamptz '2026-08-15 12:00:00+00'-(g%18)*interval '1 day'-(g%24)*interval '1 hour'
  FROM generate_series(1,130) g""")
 conn.execute("""INSERT INTO payment_sessions(order_id,provider)
  VALUES(130,'old-provider'),(130,'latest-provider'),(129,'provider-129')""")
 conn.execute("""INSERT INTO blocked_users(user_id,reason,blocked_at)
  SELECT g,'reason-'||g,timestamptz '2026-08-15 12:00:00+00'-g*interval '1 minute'
  FROM generate_series(1,110) g""")
 conn.execute("""INSERT INTO provider_health(provider,is_healthy,failed_count,
  avg_response_time,status,blocker) SELECT 'provider-'||lpad(g::text,2,'0'),g%2=0,g,
  g/10.0,CASE WHEN g%2=0 THEN 'ok' ELSE NULL END,
  CASE WHEN g%2=0 THEN NULL ELSE 'synthetic' END FROM generate_series(1,70) g""")
 conn.execute(ENVELOPE)
 conn.execute(PACKAGE)

relay_info=conninfo_to_dict(dsn)
relay_info.update(user="obsidian_relay",password="synthetic-rehearsal-only",connect_timeout="2")
relay=make_conninfo(**relay_info)

with psycopg.connect(relay) as conn:
 blocked=conn.execute("SELECT * FROM relay_admin_config_blocked_user_rows(100::smallint)").fetchall()
 assert len(blocked)==100 and blocked[0][0]==1 and blocked[-1][0]==100
 recent=conn.execute("SELECT * FROM relay_order_admin_recent(100::smallint)").fetchall()
 assert len(recent)==100
 assert [(x[6],x[0]) for x in recent]==sorted(((x[6],x[0]) for x in recent),reverse=True)
 stats=conn.execute("SELECT * FROM relay_reporting_admin_stats()").fetchone()
 assert stats[0]==130 and stats[1]==44 and stats[2]==43
 assert stats[3]==sum(x for x in range(1,131) if x%3==0)
 conn.execute("SET TimeZone='Pacific/Kiritimati'")
 analytics=conn.execute("SELECT * FROM relay_reporting_admin_analytics()").fetchone()
 assert [len(x) for x in analytics[:6]]==[15,24,32,32,64,20]
 assert set(analytics[0][0])=={'day','orders','volume','paid'}
 assert set(analytics[1][0])=={'hour','cnt'}
 assert set(analytics[2][0])=={'currency','cnt','vol'}
 assert set(analytics[3][0])=={'status','cnt'}
 assert set(analytics[4][0])=={'provider','is_healthy','failed_count','avg_response_time','status','blocker'}
 assert set(analytics[5][0])=={'order_id','currency','rub_amount','status','created_at','username','provider'}
 assert analytics[5][0]['order_id']==130 and analytics[5][0]['provider']=='latest-provider'
 assert set(analytics[6])=={'total_orders','total_volume','paid_orders','paid_volume'}
 assert analytics[6]['total_orders']==130
 conn.execute("SET TimeZone='America/Los_Angeles'")
 assert conn.execute("SELECT daily FROM relay_reporting_admin_analytics()").fetchone()[0]==analytics[0]

def denied(statement):
 try:
  with psycopg.connect(relay) as conn:conn.execute(statement)
 except psycopg.Error:return
 raise AssertionError(f"statement unexpectedly allowed: {statement}")

for statement in (
 "SELECT * FROM relay_admin_config_blocked_user_rows(0::smallint)",
 "SELECT * FROM relay_admin_config_blocked_user_rows(101::smallint)",
 "SELECT * FROM relay_order_admin_recent(NULL::smallint)",
 "SELECT * FROM orders","SELECT * FROM blocked_users",
 "SELECT * FROM payment_sessions","SELECT * FROM provider_health",
 "UPDATE blocked_users SET reason='tampered' WHERE user_id=1",
):denied(statement)

with psycopg.connect(dsn) as conn:
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname LIKE 'relay_%'
  AND has_function_privilege('obsidian_relay',p.oid,'EXECUTE')""").fetchone()[0]==9
 assert conn.execute("""SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace
  WHERE n.nspname='public' AND p.proname IN ('relay_admin_config_blocked_user_rows',
  'relay_order_admin_recent','relay_reporting_admin_stats','relay_reporting_admin_analytics')
  AND has_function_privilege('public',p.oid,'EXECUTE')""").fetchone()[0]==0
 assert conn.execute("""SELECT has_table_privilege('obsidian_relay_owner','orders','SELECT')
  OR has_table_privilege('obsidian_relay_owner','blocked_users','SELECT')
  OR has_table_privilege('obsidian_relay_owner','provider_health','SELECT')""").fetchone()==(False,)

print("E0.3 Relay P4 four bounded operator reporting bodies rehearsal: OK")
