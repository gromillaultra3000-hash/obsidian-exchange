import sqlite3,sys,tempfile,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.engagement_store import SQLiteEngagementStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'e.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,status TEXT,rub_amount REAL);INSERT INTO orders VALUES(1,7,'sent',1000);INSERT INTO orders VALUES(2,7,'completed',6000);CREATE TABLE bot_users(user_id INTEGER PRIMARY KEY,broadcast_enabled INTEGER DEFAULT 1);INSERT INTO bot_users VALUES(7,1);CREATE TABLE admin_log(id INTEGER PRIMARY KEY,admin_id INTEGER,action TEXT,target_id INTEGER,details TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);CREATE TABLE user_vip_volume(user_id INTEGER PRIMARY KEY,total_rub REAL,updated_at TEXT);CREATE TABLE rate_subscriptions(user_id INTEGER PRIMARY KEY,enabled INTEGER DEFAULT 1,last_notified REAL DEFAULT 0,last_btc REAL DEFAULT 0,last_ltc REAL DEFAULT 0,last_usdt REAL DEFAULT 0);CREATE TABLE referral_bonuses(id INTEGER PRIMARY KEY,referrer_id INTEGER,referred_id INTEGER,order_id INTEGER,bonus_amount REAL,currency TEXT,created_at TEXT);CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,total_bonus_btc REAL,bonus_paid INTEGER DEFAULT 0);INSERT INTO referrals(referrer_id,referred_id,total_bonus_btc) VALUES(9,7,.001);CREATE TABLE reviews(id INTEGER PRIMARY KEY AUTOINCREMENT,order_id INTEGER NOT NULL UNIQUE,user_id INTEGER NOT NULL,rating INTEGER,comment TEXT,status TEXT NOT NULL DEFAULT 'pending',created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
 s=SQLiteEngagementStore(p);s.log_action(9,'x',1,'d')
 for args in ((0,'x',1,'d'),(9,'',1,'d'),(9,'x'*81,1,'d'),(9,'x',1,'d'*501)):
  try:s.log_action(*args);assert False
  except ValueError:pass
 s.add_vip(7,100);s.add_vip(7,50);assert s.vip_total(7)==150
 assert s.toggle_rate(7) is False and s.toggle_rate(7) is True;s.update_rates(7,1,2,3,4);assert len(s.subscribers())==1;s.disable_rates(7);assert not s.rate_enabled(7)
 toggles=[];errors=[]
 def toggle():
  try:toggles.append(s.toggle_rate(8))
  except Exception as exc:errors.append(exc)
 threads=[threading.Thread(target=toggle) for _ in range(12)]
 [t.start() for t in threads];[t.join() for t in threads]
 assert not errors and toggles.count(True)==6 and toggles.count(False)==6 and s.rate_enabled(8)
 s.ensure_review(1,7);assert s.rate_review(1,7,5) and not s.rate_review(1,7,4)
 assert not s.comment_review(1,8,'foreign') and s.finalize_review(1,8) is None
 assert s.comment_review(1,7,'ok') and s.finalize_review(1,7)['status']=='published';assert s.review_summary()==(1,5.0)
 with sqlite3.connect(p) as c:
  c.execute("INSERT INTO referral_bonuses VALUES(1,7,8,1,12,'RUB','2026-08-09')")
  c.execute("INSERT INTO referral_bonuses VALUES(2,77,88,1,5,'RUB','2026-08-10')");c.commit()
 assert s.referral_bonus(7)==12 and s.referral_bonus(77)==5
 assert s.referral_bonus(None,'2026-08-01','2026-08-31')==17
 for args in ((None,), (7,'2026-08-01','2026-08-31'), (None,'2026-08-01',None)):
  try:s.referral_bonus(*args);assert False
  except ValueError:pass
 assert s.referral_stats(9)=={'referrals':1,'active':1,'total_bonus_btc':.001}
 assert s.credit_referral_bonus(7,.002)==9
 assert s.referral_stats(9)['total_bonus_btc']==.003
 assert s.credit_referral_bonus(999,.1) is None
 assert s.eligible_completed_count(7,5000)==1 and s.broadcast_user_ids()==[7]
 assert s.broadcast_count()==1 and s.order_customer_ids()==[7]
 wins=[];threads=[threading.Thread(target=lambda:wins.append(s.disable_broadcast(7))) for _ in range(8)]
 [t.start() for t in threads];[t.join() for t in threads]
 assert sum(wins)==1 and s.broadcast_count()==0
 with sqlite3.connect(p) as c:
  c.executemany("INSERT INTO bot_users(user_id,broadcast_enabled) VALUES(?,1)",[(u,) for u in range(1000,1505)])
  c.executemany("INSERT INTO rate_subscriptions(user_id,enabled) VALUES(?,1)",[(u,) for u in range(1000,1505)])
  c.executemany("INSERT INTO orders(order_id,user_id,status,rub_amount) VALUES(?,?,'sent',1)",[(u,u) for u in range(1000,1505)]);c.commit()
 assert s.broadcast_user_ids()==list(range(1000,1505))
 assert [int(r[0]) for r in s.subscribers()]==[8]+list(range(1000,1505))
 assert s.order_customer_ids()==[7]+list(range(1000,1505))
print('SQLite engagement repository checks: OK')
