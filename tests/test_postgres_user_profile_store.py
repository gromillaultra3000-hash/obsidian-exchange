import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres user profile store: skipped');raise SystemExit(0)
from repositories.user_profile_store import PostgresUserProfileStore
s=PostgresUserProfileStore(dsn);s.upsert_user(user_id=1,username='u',first_name='A',last_name='B');assert s.claim_referrer(referred_id=2,referrer_id=1);assert not s.claim_referrer(referred_id=2,referrer_id=3);s.set_referral_address(user_id=2,currency='BTC',address='a');s.set_referral_address(user_id=2,currency='BTC',address='b');assert s.referral_address(user_id=2,currency='BTC')=='b';assert s.referral_address(user_id=2,currency='LTC') is None
print('PostgreSQL user-profile repository checks: OK')
