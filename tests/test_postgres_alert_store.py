import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres alert store: skipped');raise SystemExit(0)
from repositories.alert_store import PostgresAlertStore
s=PostgresAlertStore(dsn);assert s.should_send('x',60) and not s.should_send('x',60);assert s.high_water('q',2) and not s.high_water('q',1) and s.high_water('q',3)
print('PostgreSQL alert repository checks: OK')
