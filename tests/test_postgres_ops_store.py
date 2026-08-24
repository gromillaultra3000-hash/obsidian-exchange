import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres ops store: skipped');raise SystemExit(0)
from repositories.ops_store import PostgresOpsStore
import psycopg
with psycopg.connect(dsn) as c:
 c.execute("TRUNCATE system_flags,audit_log,orders RESTART IDENTITY CASCADE")
 c.execute("INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status,updated_at) VALUES(1,1,'BTC',100,'addr','sent',now()-interval '30 minutes'),(2,1,'LTC',200,'addr2','sent',now()-interval '2 hours')")
s=PostgresOpsStore(dsn);s.set_flags({'payout_frozen':'1','payout_frozen_reason':'x'});assert s.get_flag('payout_frozen_reason')=='x';s.audit(event='e',details='d');s.audit(event='old',details='d')
with psycopg.connect(dsn) as c:c.execute("UPDATE audit_log SET created_at=now()-interval '91 days' WHERE event='old'")
assert s.cleanup_audit(90)==1
with psycopg.connect(dsn) as c:assert c.execute("SELECT event FROM audit_log").fetchall()==[('e',)]
assert s.payout_totals(1)==(100.0,1);assert s.payout_totals(24)==(300.0,2);assert s.recent_payout_destinations(1)==[('addr','BTC')]
print('PostgreSQL ops repository checks: OK')
