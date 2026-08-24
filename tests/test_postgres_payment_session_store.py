import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres payment session store: skipped');raise SystemExit(0)
from repositories.payment_session_store import PostgresPaymentSessionStore
import psycopg
with psycopg.connect(dsn) as c:
 c.execute("TRUNCATE payment_sessions,orders RESTART IDENTITY CASCADE")
 c.execute("INSERT INTO orders(order_id,user_id,rub_amount,crypto_address,status) VALUES(1,1,10,'a','pending'),(2,2,20,'b','pending')")
s=PostgresPaymentSessionStore(dsn);s.create_failed(token='f',order_id=1,amount=10);assert s.get('f')['status']=='failed'
s.create_invoice(token='ok',order_id=2,amount=20,provider='vertu',expires_at='2099-01-01 00:00:00+00',client_ip=None,user_agent=None,telegram_id=7,invoice_id='i',qr_payload='q',provider_payload='{}')
assert s.latest_for_order(2)['session_token']=='ok'
assert [r['provider_invoice_id'] for r in s.recent_for_order(2)]==['i']
assert s.latest_active_for_order(2)['session_token']=='ok'
assert s.token_matches_order(2,'ok') and not s.token_matches_order(1,'ok')
assert s.latest_provider_invoice(2,'vertu')['provider_invoice_id']=='i'
assert s.pending_vertu()==[{'session_token':'ok','provider_invoice_id':'i','order_id':2}]
assert s.transition('ok','awaiting_payment') and s.expire('ok') and not s.expire('ok')
assert s.latest_active_for_order(2) is None
print('PostgreSQL payment-session repository checks: OK')
