import os,sys,threading,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres sell store: skipped');raise SystemExit(0)
from repositories.sell_order_store import PostgresSellOrderStore
s=PostgresSellOrderStore(dsn);sid=s.create(user_id=1,currency='BTC',crypto_amount=1,rub_amount=100,sbp_phone='7',receive_address='a',payout_method='sbp',payout_bank='sber',payout_details='7',payout_name='User Name');assert s.claim(sid)['claimed'] and not s.claim(sid)['claimed'];assert s.record_provider(sid,provider='vertu',ref='r',status='pending');assert s.vertu_payout_by_ref('callback_r')['id']==sid;assert any(x['id']==sid for x in s.active_vertu_payouts(('paid','rejected')));assert not s.release_unreferenced(sid);assert s.mark_settled(sid);assert not s.mark_rejected(sid)
sid2=s.create(user_id=2,currency='TON',crypto_amount=2,rub_amount=200,sbp_phone='7',receive_address='b',payout_method='sbp',payout_bank='sber',payout_details='7',payout_name='User Name');sid3=s.create(user_id=3,currency='TON',crypto_amount=2,rub_amount=200,sbp_phone='7',receive_address='b',payout_method='sbp',payout_bank='sber',payout_details='7',payout_name='User Name')
barrier=threading.Barrier(2);wins=[]
def reserve(sell_id):
 barrier.wait();wins.append(PostgresSellOrderStore(dsn).reserve_txid(sell_id=sell_id,txid='same-chain-tx',expected_status='pending'))
threads=[threading.Thread(target=reserve,args=(x,)) for x in (sid2,sid3)]
[t.start() for t in threads];[t.join() for t in threads]
assert sorted(wins)==[False,True]
assert sum(1 for x in (s.get(sid2),s.get(sid3)) if x['tx_hash']=='same-chain-tx')==1
assert len(s.pending_for_user(user_id=2,currency='TON'))==1
uid=900000000+time.time_ns()%100000000;view1=s.create(user_id=uid,currency='BTC',crypto_amount=3,rub_amount=300,sbp_phone='71',receive_address='c',payout_method='card',payout_bank='sber',payout_details='4111',payout_name='User Name');view2=s.create(user_id=uid,currency='TON',crypto_amount=4,rub_amount=400,sbp_phone='72',receive_address='d',payout_method='sbp',payout_bank='tbank',payout_details='72',payout_name='User Name');foreign=s.create(user_id=uid+1,currency='BTC',crypto_amount=5,rub_amount=500,sbp_phone='73',receive_address='e',payout_method='sbp',payout_bank='sber',payout_details='73',payout_name='User Name')
with s._c() as c:c.execute("UPDATE sell_orders SET created_at='2026-01-01 00:00:00' WHERE id=ANY(%s)",([view1,view2],));c.execute("UPDATE sell_orders SET status='paid' WHERE id=%s",(view1,))
assert [x['id'] for x in s.sells_for_user(user_id=uid)]==[view2,view1];pending=s.pending_view_for_user(user_id=uid,status='pending');assert [x['id'] for x in pending]==[view2] and pending[0]['payout_details']=='72';assert not s.pending_view_for_user(user_id=uid+1,status='pending',limit=0)
print('PostgreSQL sell-order repository checks: OK')
