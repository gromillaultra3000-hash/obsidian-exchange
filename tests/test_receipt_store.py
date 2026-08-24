import sqlite3,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.receipt_store import SQLiteReceiptStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'missing.db');s=SQLiteReceiptStore(p)
 try:s.record(order_id=1,path='/x',filename='x',content_type='x',sha256='x');assert False
 except sqlite3.OperationalError:pass
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'r.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE orders(order_id INTEGER PRIMARY KEY,status TEXT,rub_amount REAL,user_id INTEGER,username TEXT,receipt_sent_at TEXT,verification_requested TEXT);CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,session_token TEXT,provider TEXT,provider_invoice_id TEXT,provider_payload TEXT,status TEXT);CREATE TABLE order_receipts(order_id INTEGER PRIMARY KEY,path TEXT,filename TEXT,content_type TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,dispute_opened_at TEXT,sha256 TEXT);INSERT INTO orders VALUES(1,'pending',10,2,'u',NULL,'video');INSERT INTO orders VALUES(2,'expired',10,2,'u',NULL,NULL);INSERT INTO orders VALUES(3,'expired',10,2,'u',NULL,NULL);INSERT INTO orders VALUES(4,'expired',10,2,'u',NULL,NULL);INSERT INTO payment_sessions VALUES(1,1,'own','brabus:vietqr','inv','{}','invoice_created');""")
 s=SQLiteReceiptStore(p);s.record(order_id=1,path='/x',filename='a.pdf',content_type='application/pdf',sha256='h');assert s.get(1)['path']=='/x' and s.state(1)=='stored' and s.state(999)=='';assert s.authorized_state(1,user_id=2)=='stored' and s.authorized_state(1,user_id=3)=='';assert s.authorized_state(1,session_token='own')=='stored' and s.authorized_state(1,session_token='missing')=='';assert s.mark_sent(1) and s.state(1)=='sent' and not s.mark_sent(1);assert s.claim_dispute(1) and not s.claim_dispute(1);assert s.sessions(1)[0]['provider']=='brabus:vietqr';assert s.order_guard_fields(1)['verification_requested']=='video';assert s.fraud_profile(1)=={'user_id':2,'expired':3,'paid':0}
print('SQLite receipt repository checks: OK')
