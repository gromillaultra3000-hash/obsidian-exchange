import os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres limit store: skipped');raise SystemExit(0)
from repositories.limit_order_store import PostgresLimitOrderStore
s=PostgresLimitOrderStore(dsn);lid=s.create(user_id=1,currency='BTC',target_rate=10,direction='below',rub_amount=100,destination='dest',payment_method='sbp',expires_at=datetime.now(timezone.utc)+timedelta(days=1));listed=s.for_user(1);match=next(r for r in listed if r[0]==lid);assert match[2]=='below' and isinstance(match[6],str);row=next(r for r in s.active() if r['id']==lid)
assert s.trigger(ident=lid,expected_expires_at=row['expires_at'],destination='dest',agreed_rate=10,agreed_crypto_amount=10)['action']=='triggered'
assert s.trigger(ident=lid,expected_expires_at=row['expires_at'],destination='dest',agreed_rate=10,agreed_crypto_amount=10)['action']=='lost_race'
print('PostgreSQL limit-order repository checks: OK')
