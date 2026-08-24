import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres receipt store: skipped');raise SystemExit(0)
from repositories.receipt_store import PostgresReceiptStore
import psycopg
with psycopg.connect(dsn) as c:
 c.execute("TRUNCATE order_receipts,payment_sessions,orders RESTART IDENTITY CASCADE")
 c.execute("INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status,verification_requested) VALUES(1,2,'BTC',10,'addr','pending','video'),(2,2,'BTC',10,'addr','expired',NULL),(3,2,'BTC',10,'addr','expired',NULL),(4,2,'BTC',10,'addr','expired',NULL)")
 c.execute("INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,provider_invoice_id,provider_payload) VALUES('t',1,10,'brabus:vietqr','invoice_created','inv','{}')")
s=PostgresReceiptStore(dsn);s.record(order_id=1,path='/x',filename='a.pdf',content_type='application/pdf',sha256='h');assert s.get(1)['path']=='/x' and s.state(1)=='stored' and s.state(999)=='' and s.mark_sent(1) and s.state(1)=='sent' and not s.mark_sent(1);assert s.claim_dispute(1) and not s.claim_dispute(1);assert s.sessions(1)[0]['provider']=='brabus:vietqr';assert s.order_guard_fields(1)['verification_requested']=='video';assert s.fraud_profile(1)=={'user_id':2,'expired':3,'paid':0}
print('PostgreSQL receipt repository checks: OK')
