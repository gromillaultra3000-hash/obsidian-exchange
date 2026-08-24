import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres admin config store: skipped');raise SystemExit(0)
from repositories.admin_config_store import PostgresAdminConfigStore
s=PostgresAdminConfigStore(dsn);s.set_staff(role='operator',user_id=1,username='u',added_by=9);assert 1 in s.active_staff_ids(role='operator');rows=s.staff_rows(role='operator');assert rows[0][0:2]==(1,'u') and isinstance(rows[0][2],str) and rows[0][3] is True;assert s.deactivate_staff(role='operator',user_id=1);assert 1 not in s.active_staff_ids(role='operator');assert s.block_user(user_id=2) and s.is_user_blocked(2);assert s.blocked_user_rows()[0][0]==2 and isinstance(s.blocked_user_rows()[0][2],str);assert s.unblock_user(2) and not s.is_user_blocked(2);s.block_address(address='a',reason='x',blocked_by=9);assert s.unblock_addresses(['a'])==1;s.set_reserve(currency='BTC',amount=2)
print('PostgreSQL admin-config repository checks: OK')
