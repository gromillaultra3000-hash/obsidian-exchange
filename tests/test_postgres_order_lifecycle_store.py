import os,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"relay"))
from repositories.order_lifecycle_store import PostgresOrderLifecycleStore
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres order lifecycle store: skipped');raise SystemExit(0)
s=PostgresOrderLifecycleStore(dsn);ids=list(range(993101,993107))
with s._c() as c:
 c.execute("DELETE FROM order_lifecycle_work WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM sent_notifications WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM order_receipts WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM payment_sessions WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM orders WHERE order_id=ANY(%s)",(ids,))
 c.cursor().executemany("INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status,created_at) VALUES(%s,7,'BTC',1000,'a','pending','2026-01-01')",[(i,) for i in ids[:5]])
 c.execute("INSERT INTO order_receipts(order_id,path,filename,content_type) VALUES(%s,'p','f','x')",(ids[1],))
 c.cursor().executemany("INSERT INTO payment_sessions(session_token,order_id,amount,provider,status,provider_invoice_id,expires_at) VALUES(%s,%s,1,%s,%s,%s,%s)",[
  ('lc-active',ids[2],'vertu','invoice_created','v1','2099-01-01'),('lc-brabus',ids[0],'brabus:card','expired','b1','2026-01-01'),('lc-dead',ids[3],'vertu','invoice_created','v2','2099-01-01')])
results=[];ts=[threading.Thread(target=lambda:results.append(s.expire_due())) for _ in range(6)]
[t.start() for t in ts];[t.join() for t in ts];assert sum(results)==2
assert s.fail_session(ids[3],'lc-dead','vertu',detail='declined')['claimed']
assert s.fail_session(ids[3],'lc-dead','vertu')['action']=='conflict'
jobs=[]
def claim():
 item=s.claim_work(kind='order_expired_notify')
 if item:jobs.append(item)
ts=[threading.Thread(target=claim) for _ in range(6)];[t.start() for t in ts];[t.join() for t in ts]
assert len(jobs)==2 and len({j['id'] for j in jobs})==2
assert all(s.complete_work(j['id']) for j in jobs)
with s._c() as c:
 assert c.execute("SELECT status FROM orders WHERE order_id=%s",(ids[1],)).fetchone()['status']=='pending'
 assert c.execute("SELECT status FROM orders WHERE order_id=%s",(ids[2],)).fetchone()['status']=='pending'
 assert c.execute("SELECT count(*) FROM order_lifecycle_work WHERE order_id=%s AND kind='provider_cancel'",(ids[0],)).fetchone()['count']==1
 # PostgreSQL fault injection: outbox failure rolls back expiry and marker.
 c.execute("INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status,created_at) "
           "VALUES(%s,7,'BTC',1,'a','pending','2026-01-01')",(ids[5],))
 c.execute("CREATE OR REPLACE FUNCTION lifecycle_test_fault() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN "
           "IF NEW.order_id=%s THEN RAISE EXCEPTION 'fault'; END IF; RETURN NEW; END$$",(ids[5],))
 c.execute("CREATE TRIGGER lifecycle_test_fault BEFORE INSERT ON order_lifecycle_work "
           "FOR EACH ROW EXECUTE FUNCTION lifecycle_test_fault()")
try:s.expire_due();raise AssertionError('PostgreSQL fault swallowed')
except Exception as exc:assert 'fault' in str(exc)
with s._c() as c:
 assert c.execute("SELECT status FROM orders WHERE order_id=%s",(ids[5],)).fetchone()['status']=='pending'
 assert c.execute("SELECT 1 FROM sent_notifications WHERE order_id=%s",(ids[5],)).fetchone() is None
 c.execute("DROP TRIGGER lifecycle_test_fault ON order_lifecycle_work")
 c.execute("DROP FUNCTION lifecycle_test_fault()")
 c.execute("DELETE FROM order_lifecycle_work WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM sent_notifications WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM order_receipts WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM payment_sessions WHERE order_id=ANY(%s)",(ids,));c.execute("DELETE FROM orders WHERE order_id=ANY(%s)",(ids,))
print('PostgreSQL order-lifecycle repository checks: OK')
