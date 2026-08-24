import sqlite3,sys,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"relay"))
from repositories.order_lifecycle_store import SQLiteOrderLifecycleStore

def seed(path):
 with sqlite3.connect(path) as c:
  c.executescript("""CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,currency TEXT,rub_amount REAL,status TEXT,created_at TEXT,updated_at TEXT);
  CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,session_token TEXT UNIQUE,order_id INTEGER,provider TEXT,status TEXT,provider_invoice_id TEXT,created_at TEXT,updated_at TEXT,expires_at TEXT);
  CREATE TABLE order_receipts(order_id INTEGER PRIMARY KEY);CREATE TABLE sent_notifications(order_id INTEGER,event TEXT,PRIMARY KEY(order_id,event));""")
  c.executescript((ROOT/'deploy/sqlite/021_order_lifecycle.sql').read_text())
  c.executemany("INSERT INTO orders VALUES(?,?,?,?,?,'2026-01-01',NULL)",[(1,7,'BTC',1000,'pending'),(2,7,'BTC',1000,'pending'),(3,7,'BTC',1000,'pending'),(4,7,'BTC',1000,'pending'),(5,7,'BTC',1000,'pending')])
  c.execute("INSERT INTO order_receipts VALUES(2)")
  c.executemany("INSERT INTO payment_sessions(session_token,order_id,provider,status,provider_invoice_id,expires_at) VALUES(?,?,?,?,?,?)",[
   ('active',3,'vertu','invoice_created','v1','2099-01-01'),('brabus',1,'brabus:card','expired','b1','2026-01-01'),('dead',4,'vertu','invoice_created','v2','2099-01-01')])

with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'db');seed(p);s=SQLiteOrderLifecycleStore(p)
 results=[];ts=[threading.Thread(target=lambda:results.append(s.expire_due())) for _ in range(6)]
 [t.start() for t in ts];[t.join() for t in ts];assert sum(results)==2
 with sqlite3.connect(p) as c:
  assert dict(c.execute("SELECT order_id,status FROM orders"))=={1:'expired',2:'pending',3:'pending',4:'pending',5:'expired'}
  kinds=c.execute("SELECT kind,order_id FROM order_lifecycle_work ORDER BY kind,order_id").fetchall()
  assert kinds==[('order_expired_notify',1),('order_expired_notify',5),('provider_cancel',1)]
 r=s.fail_session(4,'dead','vertu',detail='declined');assert r['action']=='failed' and r['claimed']
 assert s.fail_session(4,'dead','vertu')['action']=='conflict'
 job=s.claim_work(kind='session_dead_admin');assert job['order_id']==4 and not job['has_receipt']
 assert s.retry_work(job['id']);job=s.claim_work(kind='session_dead_admin');assert job['attempts']==2
 assert s.complete_work(job['id']) and not s.complete_work(job['id'])
 # A durable-work insertion fault rolls back both expiry and its marker.
 with sqlite3.connect(p) as c:
  c.execute("INSERT INTO orders VALUES(9,7,'BTC',1,'pending','2026-01-01',NULL)")
  c.execute("CREATE TRIGGER fail_work BEFORE INSERT ON order_lifecycle_work WHEN NEW.order_id=9 BEGIN SELECT RAISE(ABORT,'fault'); END")
 try:s.expire_due();raise AssertionError('fault swallowed')
 except sqlite3.IntegrityError:pass
 with sqlite3.connect(p) as c:
  assert c.execute("SELECT status FROM orders WHERE order_id=9").fetchone()==('pending',)
  assert c.execute("SELECT 1 FROM sent_notifications WHERE order_id=9").fetchone() is None
print('SQLite order-lifecycle repository checks: OK')
