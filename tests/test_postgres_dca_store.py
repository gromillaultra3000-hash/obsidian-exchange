import os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres DCA store: skipped');raise SystemExit(0)
from repositories.dca_store import PostgresDcaStore
s=PostgresDcaStore(dsn);past=datetime.now(timezone.utc)-timedelta(minutes=1);did=s.create(user_id=1,currency='BTC',rub_amount=100,destination='dest',interval_days=7,next_run=past);listed=s.for_user(1);match=next(r for r in listed if r[0]==did);assert match[1]=='BTC' and isinstance(match[4],str);row=next(r for r in s.due() if r['id']==did);future=datetime.now(timezone.utc)+timedelta(days=7)
assert s.run_due(schedule_id=did,expected_next_run=row['next_run'],destination='dest',agreed_rate=10,agreed_crypto_amount=10,next_run=future)['action']=='created'
assert s.run_due(schedule_id=did,expected_next_run=row['next_run'],destination='dest',agreed_rate=10,agreed_crypto_amount=10,next_run=future)['action']=='lost_race'
print('PostgreSQL DCA repository checks: OK')
