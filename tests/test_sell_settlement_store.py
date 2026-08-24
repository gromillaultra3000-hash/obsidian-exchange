import sqlite3,sys,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.sell_settlement_store import SQLiteSellSettlementStore

def seed(path):
 with sqlite3.connect(path) as c:
  c.executescript("""CREATE TABLE sell_orders(id INTEGER PRIMARY KEY,user_id INTEGER,rub_amount REAL,status TEXT,payout_provider TEXT,payout_ref TEXT,payout_status TEXT,updated_at TEXT);
  CREATE TABLE user_vip_volume(user_id INTEGER PRIMARY KEY,total_rub REAL,updated_at TEXT);
  INSERT INTO sell_orders VALUES(1,7,2500,'paying','vertu','v-1','paid',NULL);
  INSERT INTO sell_orders VALUES(2,7,3000,'paying','vertu','v-2','pending',NULL);
  INSERT INTO sell_orders VALUES(3,8,4000,'paying','vertu','v-3','paid',NULL);""")
  c.executescript((ROOT/'deploy/sqlite/022_sell_settlement.sql').read_text())
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'db');seed(p);s=SQLiteSellSettlementStore(p);results=[]
 ts=[threading.Thread(target=lambda:results.append(s.settle_vertu(1,payout_ref='v-1')['action'])) for _ in range(8)]
 [t.start() for t in ts];[t.join() for t in ts]
 assert results.count('settled')==1 and results.count('already_settled')==7
 assert s.settle_vertu(2,payout_ref='v-2')['action']=='evidence_conflict'
 with sqlite3.connect(p) as c:
  assert c.execute("SELECT status FROM sell_orders WHERE id=1").fetchone()==('paid',)
  assert c.execute("SELECT total_rub FROM user_vip_volume WHERE user_id=7").fetchone()==(2500.0,)
  assert c.execute("SELECT count(*) FROM sell_settlement_ledger").fetchone()==(1,)
 item=s.claim_notification();assert item['sell_id']==1 and item['attempts']==1
 assert s.retry_notification(item['id']);item=s.claim_notification();assert item['attempts']==2
 assert s.mark_notification_sent(item['id']) and not s.mark_notification_sent(item['id'])
 # Final outbox failure must roll back sell status, immutable ledger and VIP.
 with sqlite3.connect(p) as c:c.execute("CREATE TRIGGER fail_sell_outbox BEFORE INSERT ON sell_settlement_outbox WHEN NEW.sell_id=3 BEGIN SELECT RAISE(ABORT,'fault'); END")
 try:s.settle_vertu(3,payout_ref='v-3');raise AssertionError('fault swallowed')
 except sqlite3.IntegrityError:pass
 with sqlite3.connect(p) as c:
  assert c.execute("SELECT status FROM sell_orders WHERE id=3").fetchone()==('paying',)
  assert c.execute("SELECT 1 FROM sell_settlement_ledger WHERE sell_id=3").fetchone() is None
  assert c.execute("SELECT 1 FROM user_vip_volume WHERE user_id=8").fetchone() is None
print('SQLite sell-settlement repository checks: OK')
