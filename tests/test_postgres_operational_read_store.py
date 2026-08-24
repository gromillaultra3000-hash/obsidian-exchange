import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.environ['TEST_POSTGRES_DSN'];import psycopg
from repositories.operational_read_store import PostgresOperationalReadStore
with psycopg.connect(dsn) as c:
 c.execute("TRUNCATE order_receipts,payment_sessions,sent_notifications,reserves,orders RESTART IDENTITY CASCADE")
 c.execute("INSERT INTO reserves(currency,amount) VALUES('BTC',2)")
 c.execute("INSERT INTO orders(order_id,user_id,username,rub_amount,currency,crypto_address,network,status,created_at,updated_at,paid_btc_tx,receipt_sent_at,agreed_crypto_amount) VALUES(1,7,'u',1000,'BTC','addr','MAINNET','paid',now()-interval '2 hours',NULL,NULL,NULL,0.01),(2,7,'u',500,'BTC','addr','MAINNET','expired',now()-interval '2 hours',now(),NULL,NULL,NULL),(3,7,'u',300,'BTC','fresh','MAINNET','paid',now()-interval '5 minutes',NULL,NULL,NULL,0.003),(4,7,'u',400,'BTC','old','MAINNET','paid',now()-interval '15 days',NULL,NULL,NULL,0.004),(5,7,'u',600,'BTC','sent','MAINNET','sent',now()-interval '2 days',NULL,'ABCDEF',NULL,0.006)")
 c.execute("INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,created_at,updated_at,expires_at) VALUES('t',2,500,'p','expired',now()-interval '1 hour',now()-interval '50 minutes',now())")
 c.execute("INSERT INTO order_receipts(order_id,path,filename,content_type,created_at) VALUES(2,'/x','x.pdf','application/pdf',now()-interval '2 hours')")
s=PostgresOperationalReadStore(dsn);assert s.reserves()[0][0]=='BTC';assert s.paid_deals(7,('paid','sent'))==4;assert s.paid_deals(7,('failed','cancelled'))==0;assert s.client_order_counts(7,('paid','sent'))=={'created':5,'paid':4};assert s.payout_rows(1)[0]['order_id']==1;assert s.receipt_queue_rows()[0]['order_id']==2;r=s.conversion_snapshot(window_hours=3,stuck_minutes=45,undelivered_minutes=20,unresolved_minutes=90,unresolved_days=7);assert r['issued']==1 and r['early_expiry']==1 and r['stuck_payouts'][0]['order_id']==4
evidence=s.payout_evidence_orders(min_age_minutes=45,max_age_days=14);assert [r['order_id'] for r in evidence]==[1];assert evidence[0]['paid_ts']>0 and float(evidence[0]['agreed_crypto_amount'])==0.01
assert s.payout_evidence_order(1)['status']=='paid' and s.payout_evidence_order(999) is None
assert s.used_payout_txids()==['ABCDEF']
assert [r['order_id'] for r in s.chain_reconciliation_orders(3)]==[5,3,1]
print('PostgreSQL operational read repository checks: OK')
