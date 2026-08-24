import os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres swap store: skipped');raise SystemExit(0)
from repositories.swap_store import PostgresSwapStore
s=PostgresSwapStore(dsn);s.create(token='t',user_id=1,coin_from='BTC',coin_to='ETH',amount_from=1,address_to='a',external_id='x',external_url='u',status='waiting',provider='swapuz',deposit_address='d');rows=s.unfinished(('finished','failed'));match=next(r for r in rows if r[0]=='t');assert match[7]==1.0 and isinstance(match[7],float);assert s.unfinished(())==[];assert s.transition(token='t',expected_status='waiting',new_status='confirming');assert not s.transition(token='t',expected_status='waiting',new_status='failed')
tag=str(time.time_ns());wid=900000000+time.time_ns()%100000000;old='web-old-'+tag;new='web-new-'+tag;foreign='foreign-'+tag;s.create(token=old,user_id=-wid,web_user_id=wid,coin_from='BTC',coin_to='LTC',amount_from=2,address_to='wa',external_id='wx1-'+tag,external_url='wu1',status='waiting',provider='trocador',deposit_address='wd1');s.create(token=new,user_id=wid+10,web_user_id=0,coin_from='ETH',coin_to='BTC',amount_from=3,address_to='wb',external_id='wx2-'+tag,external_url='wu2',status='confirming',provider='swapuz',deposit_address='wd2');s.create(token=foreign,user_id=wid+11,web_user_id=wid+1,coin_from='TON',coin_to='BTC',amount_from=4,address_to='wc',external_id='wx3-'+tag,external_url='wu3',status='waiting',provider='swapuz',deposit_address='wd3')
with s._c() as c:c.execute("UPDATE swap_sessions SET created_at='2026-01-01 00:00:00' WHERE session_token=ANY(%s)",([old,new],))
assert [x['token'] for x in s.swaps_for_web_user(web_user_id=wid,user_id=wid+10)]==[new,old];assert [x['token'] for x in s.swaps_for_web_user(web_user_id=wid,user_id=None)]==[old];assert s.get_by_token(foreign)['external_id']=='wx3-'+tag;assert s.get_by_external_id('wx2-'+tag)['session_token']==new;assert s.get_by_token('missing-'+tag) is None
print('PostgreSQL swap repository checks: OK')
