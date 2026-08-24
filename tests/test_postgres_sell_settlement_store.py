import os,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.sell_settlement_store import PostgresSellSettlementStore
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres sell settlement store: skipped');raise SystemExit(0)
s=PostgresSellSettlementStore(dsn);ids=[994101,994102,994103];users=[99411,99412]
with s._c() as c:
 c.execute("DELETE FROM sell_settlement_outbox WHERE sell_id=ANY(%s)",(ids,));c.execute("DELETE FROM sell_settlement_ledger WHERE sell_id=ANY(%s)",(ids,));c.execute("DELETE FROM sell_orders WHERE id=ANY(%s)",(ids,));c.execute("DELETE FROM user_vip_volume WHERE user_id=ANY(%s)",(users,))
 c.cursor().executemany("INSERT INTO sell_orders(id,user_id,currency,crypto_amount,rub_amount,sbp_phone,receive_address,status,payout_provider,payout_ref,payout_status) VALUES(%s,%s,'BTC',1,%s,'7','a','paying','vertu',%s,%s)",[(ids[0],users[0],2500,'v-1','paid'),(ids[1],users[0],3000,'v-2','pending'),(ids[2],users[1],4000,'v-3','paid')])
results=[];ts=[threading.Thread(target=lambda:results.append(s.settle_vertu(ids[0],payout_ref='v-1')['action'])) for _ in range(8)]
[t.start() for t in ts];[t.join() for t in ts]
assert results.count('settled')==1 and results.count('already_settled')==7
assert s.settle_vertu(ids[1],payout_ref='v-2')['action']=='evidence_conflict'
claimed=[]
def claim():
 item=s.claim_notification()
 if item:claimed.append(item)
ts=[threading.Thread(target=claim) for _ in range(5)];[t.start() for t in ts];[t.join() for t in ts]
assert len(claimed)==1 and s.mark_notification_sent(claimed[0]['id'])
with s._c() as c:
 assert float(c.execute("SELECT total_rub FROM user_vip_volume WHERE user_id=%s",(users[0],)).fetchone()['total_rub'])==2500
 c.execute("CREATE OR REPLACE FUNCTION sell_settlement_test_fault() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.sell_id=%s THEN RAISE EXCEPTION 'fault'; END IF; RETURN NEW; END$$",(ids[2],))
 c.execute("CREATE TRIGGER sell_settlement_test_fault BEFORE INSERT ON sell_settlement_outbox FOR EACH ROW EXECUTE FUNCTION sell_settlement_test_fault()")
try:s.settle_vertu(ids[2],payout_ref='v-3');raise AssertionError('fault swallowed')
except Exception as exc:assert 'fault' in str(exc)
with s._c() as c:
 assert c.execute("SELECT status FROM sell_orders WHERE id=%s",(ids[2],)).fetchone()['status']=='paying'
 assert c.execute("SELECT 1 FROM sell_settlement_ledger WHERE sell_id=%s",(ids[2],)).fetchone() is None
 assert c.execute("SELECT 1 FROM user_vip_volume WHERE user_id=%s",(users[1],)).fetchone() is None
 c.execute("DROP TRIGGER sell_settlement_test_fault ON sell_settlement_outbox");c.execute("DROP FUNCTION sell_settlement_test_fault()")
 c.execute("DELETE FROM sell_settlement_outbox WHERE sell_id=ANY(%s)",(ids,));c.execute("DELETE FROM sell_settlement_ledger WHERE sell_id=ANY(%s)",(ids,));c.execute("DELETE FROM sell_orders WHERE id=ANY(%s)",(ids,));c.execute("DELETE FROM user_vip_volume WHERE user_id=ANY(%s)",(users,))
print('PostgreSQL sell-settlement repository checks: OK')
