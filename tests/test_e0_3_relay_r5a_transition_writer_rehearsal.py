import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn: print('R5A skipped');raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict,make_conninfo
R=Path(__file__).resolve().parents[1];E=(R/'deploy/postgres/proposals/028_e0_relay_acl_envelope.sql').read_text();P=(R/'deploy/postgres/proposals/041_e0_relay_r5a_transition_writers.sql').read_text()
with psycopg.connect(dsn) as c:
 c.execute("CREATE TABLE orders(order_id bigserial PRIMARY KEY,user_id bigint,status text,rub_amount numeric,verification_requested text,updated_at timestamptz)")
 c.execute("CREATE TABLE sell_orders(id bigserial PRIMARY KEY,status text,updated_at timestamptz)")
 c.execute("CREATE TABLE swap_sessions(id bigserial PRIMARY KEY,session_token text UNIQUE,status text,updated_at timestamptz)")
 c.execute("CREATE TABLE referral_addresses(user_id bigint PRIMARY KEY,currency text,address text)")
 c.execute("CREATE TABLE payment_notification_outbox(id bigserial PRIMARY KEY,order_id bigint,recipient_id bigint,payload jsonb,state text,attempts integer,claimed_at timestamptz,updated_at timestamptz)")
 c.execute("CREATE TABLE payment_transition_audit(id bigserial PRIMARY KEY,order_id bigint,from_status text,to_status text,evidence text)");c.execute("CREATE TABLE support_tickets(ticket_id bigserial PRIMARY KEY,web_user_id bigint,subject text,status text)")
 c.execute("INSERT INTO orders(order_id,user_id,status) VALUES(1,7,'pending')");c.execute("INSERT INTO sell_orders(id,status) VALUES(1,'pending')");c.execute("INSERT INTO swap_sessions(session_token,status) VALUES('token-00000000000001','waiting')");c.execute(E);c.execute(P)
i=conninfo_to_dict(dsn);i.update(user='obsidian_relay',password='synthetic-rehearsal-only');relay=make_conninfo(**i)
def call(sql):
 with psycopg.connect(relay) as c:return c.execute(sql).fetchone()[0]
with ThreadPoolExecutor(max_workers=12) as p:r=list(p.map(lambda _:call("SELECT action FROM relay_order_request_verification(1,'video')"),range(12)))
assert r.count('requested')==1 and r.count('conflict')==11
with ThreadPoolExecutor(max_workers=12) as p:r=list(p.map(lambda _:call("SELECT relay_sell_cancel_pending(1)"),range(12)))
assert r.count(True)==1 and r.count(False)==11
assert call("SELECT relay_swap_transition('token-00000000000001','waiting','completed')") is True
assert call("SELECT relay_swap_transition('token-00000000000001','waiting','failed')") is False
assert call("SELECT relay_swap_transition('missing-token-000000','same','same')") is True
call("SELECT relay_user_profile_set_referral_address(9,'btc','addr1')");call("SELECT relay_user_profile_set_referral_address(9,'ltc','addr2')")
with psycopg.connect(dsn) as c:
 assert c.execute("SELECT currency,address FROM referral_addresses WHERE user_id=9").fetchone()==('LTC','addr2')
 assert c.execute("SELECT count(*) FROM pg_proc p WHERE p.proname LIKE 'relay_%' AND has_function_privilege('public',p.oid,'EXECUTE')").fetchone()[0]==0
for s in ('SELECT * FROM orders','UPDATE sell_orders SET status=\'paid\'','SELECT * FROM referral_addresses'):
 try:
  with psycopg.connect(relay) as c:c.execute(s)
 except psycopg.Error:continue
 raise AssertionError('raw access allowed')
print('E0.3 Relay R5A transition writer rehearsal: OK')
