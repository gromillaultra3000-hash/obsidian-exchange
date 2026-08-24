import os,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.operational_read_store import SQLiteOperationalReadStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'o.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,username TEXT,rub_amount REAL,currency TEXT,crypto_address TEXT,network TEXT,status TEXT,created_at TEXT,updated_at TEXT,paid_btc_tx TEXT,receipt_sent_at TEXT,agreed_crypto_amount REAL);CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,provider TEXT,status TEXT,created_at TEXT,updated_at TEXT,expires_at TEXT);CREATE TABLE order_receipts(order_id INTEGER PRIMARY KEY,created_at TEXT);CREATE TABLE sent_notifications(order_id INTEGER,event TEXT);CREATE TABLE reserves(currency TEXT,amount REAL);INSERT INTO reserves VALUES('BTC',2);INSERT INTO orders VALUES(1,7,'u',1000,'BTC','addr','MAINNET','paid',datetime('now','-2 hours'),NULL,NULL,NULL,0.01);INSERT INTO orders VALUES(2,7,'u',500,'BTC','addr','MAINNET','expired',datetime('now','-2 hours'),datetime('now'),NULL,NULL,NULL);INSERT INTO orders VALUES(3,7,'u',300,'BTC','fresh','MAINNET','paid',datetime('now','-5 minutes'),NULL,NULL,NULL,0.003);INSERT INTO orders VALUES(4,7,'u',400,'BTC','old','MAINNET','paid',datetime('now','-15 days'),NULL,NULL,NULL,0.004);INSERT INTO orders VALUES(5,7,'u',600,'BTC','sent','MAINNET','sent',datetime('now','-2 days'),NULL,'ABCDEF',NULL,0.006);INSERT INTO payment_sessions VALUES(1,2,'p','expired',datetime('now','-1 hour'),datetime('now','-50 minutes'),datetime('now'));INSERT INTO order_receipts VALUES(2,datetime('now','-2 hours'));""")
 s=SQLiteOperationalReadStore(p);assert s.reserves()==[('BTC',2.0)];assert s.paid_deals(7,('paid','sent'))==4;assert s.paid_deals(7,('failed','cancelled'))==0;assert s.client_order_counts(7,('paid','sent'))=={'created':5,'paid':4};assert s.payout_rows(1)[0]['order_id']==1;assert s.receipt_queue_rows()[0]['order_id']==2;r=s.conversion_snapshot(window_hours=3,stuck_minutes=45,undelivered_minutes=20,unresolved_minutes=90,unresolved_days=7);assert r['issued']==1 and r['early_expiry']==1 and r['stuck_payouts'][0]['order_id']==4
 evidence=s.payout_evidence_orders(min_age_minutes=45,max_age_days=14);assert [r['order_id'] for r in evidence]==[1];assert evidence[0]['paid_ts']>0 and evidence[0]['agreed_crypto_amount']==0.01
 assert s.payout_evidence_order(1)['status']=='paid' and s.payout_evidence_order(999) is None
 assert s.used_payout_txids()==['ABCDEF']
 assert [r['order_id'] for r in s.chain_reconciliation_orders(3)]==[5,3,1]
os.environ['DATABASE_URL']='postgresql://example.invalid/db'
try:
 from repositories.operational_read_store import from_environment
 try:from_environment(sqlite_path='ignored');raise AssertionError('gate missing')
 except RuntimeError as e:assert str(e)=='postgres_operational_read_store_not_enabled'
finally:os.environ.pop('DATABASE_URL',None)
print('SQLite operational read repository checks: OK')
