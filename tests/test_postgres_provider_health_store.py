import os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres provider health store: skipped');raise SystemExit(0)
from repositories.provider_health_store import PostgresProviderHealthStore
s=PostgresProviderHealthStore(dsn);s.record(provider='P',success=False,response_time=1,max_fails=2,status='NETWORK',blocker='x');s.record(provider='P',success=False,response_time=2,max_fails=2,status='NETWORK',blocker='x');r=s.all_health()[0];assert r['provider']=='P' and r['failed_count']==2;assert s.attempt_stats('P',datetime.now(timezone.utc)-timedelta(hours=1))['count']==2;assert s.reset('P');assert not s.reset('missing')
print('PostgreSQL provider-health repository checks: OK')
