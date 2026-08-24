import os,sys,time
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres promo admin store: skipped');raise SystemExit(0)
from repositories.promo_admin_store import PostgresPromoAdminStore
s=PostgresPromoAdminStore(dsn);suffix=str(time.time_ns());code_a='A'+suffix;code_b='B'+suffix;aid=s.create(code=code_a,discount=1,max_uses=2,valid_until=datetime.now(timezone.utc)+timedelta(days=1));assert s.issue_winback(order_id=int(suffix[-9:]),code=code_b,discount=2,valid_hours=3);assert s.issue_winback(order_id=int(suffix[-9:]),code='C'+suffix,discount=2,valid_hours=3) is None
assert s.validate_for_user(code=code_a.lower(),user_id=7)=={'code_id':aid,'discount':1.0};assert code_b in [x[0] for x in s.active(limit=100)]
print('PostgreSQL promo-admin repository checks: OK')
