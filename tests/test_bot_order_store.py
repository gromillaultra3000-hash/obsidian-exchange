import sqlite3,sys,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"relay"))
from repositories.bot_order_store import SQLiteBotOrderStore

with tempfile.TemporaryDirectory() as td:
 path=str(Path(td)/"bot-orders.db")
 with sqlite3.connect(path) as c:
  c.executescript("""
  CREATE TABLE orders(order_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,
   currency TEXT,rub_amount REAL,crypto_address TEXT,status TEXT,network TEXT,agreed_rate REAL,
   agreed_crypto_amount REAL,agreed_at TEXT);
  CREATE TABLE rate_locks(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,currency TEXT,
   locked_rate REAL,fee_rub REAL,locked_until TEXT,used INTEGER DEFAULT 0,order_id INTEGER,
   created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE promo_codes(id INTEGER PRIMARY KEY,discount_percent REAL,max_uses INTEGER,
   uses_count INTEGER,is_active INTEGER,valid_until TEXT);
  CREATE TABLE promo_uses(id INTEGER PRIMARY KEY,code_id INTEGER,user_id INTEGER,order_id INTEGER,
   UNIQUE(code_id,user_id));
  INSERT INTO promo_codes VALUES(1,5,1,0,1,datetime('now','+1 day'));
  """)
 store=SQLiteBotOrderStore(path)
 future=datetime.now(timezone.utc)+timedelta(minutes=15)
 lid=store.replace_rate_lock(user_id=7,currency="BTC",locked_rate=10_000_000,
                             fee_rub=100,locked_until=future)
 assert store.active_rate_lock(7,"BTC")["lock_id"]==lid
 result=store.create_order(user_id=7,username="u",currency="BTC",rub_amount=10000,
   destination="dest",network=None,preferred_rate=12_000_000,preferred_crypto_amount=.00083333,
   fallback_rate=13_000_000,fallback_crypto_amount=.00076923,lock_id=lid)
 assert result["lock_used"] and result["agreed_rate"]==12_000_000
 assert store.active_rate_lock(7,"BTC") is None
 # A stale/racing lock can never grant its quote twice.
 lost=store.create_order(user_id=7,username="u",currency="BTC",rub_amount=10000,
   destination="dest2",network=None,preferred_rate=12_000_000,preferred_crypto_amount=.00083333,
   fallback_rate=13_000_000,fallback_crypto_amount=.00076923,lock_id=lid)
 assert not lost["lock_used"] and lost["agreed_rate"]==13_000_000
 promo=store.create_order(user_id=10,username="p",currency="BTC",rub_amount=10000,
   destination="promo",network=None,preferred_rate=9,preferred_crypto_amount=2,
   fallback_rate=9,fallback_crypto_amount=2,lock_id=None,promo_id=1,
   lock_no_promo_rate=10,lock_no_promo_crypto_amount=1,
   regular_no_promo_rate=10,regular_no_promo_crypto_amount=1)
 assert promo["promo_used"] and promo["agreed_rate"]==9
 raced=store.create_order(user_id=11,username="p2",currency="BTC",rub_amount=10000,
   destination="promo2",network=None,preferred_rate=9,preferred_crypto_amount=2,
   fallback_rate=9,fallback_crypto_amount=2,lock_id=None,promo_id=1,
   lock_no_promo_rate=10,lock_no_promo_crypto_amount=1,
   regular_no_promo_rate=10,regular_no_promo_crypto_amount=1)
 assert not raced["promo_used"] and raced["agreed_rate"]==10
 with sqlite3.connect(path) as c:
  assert c.execute("SELECT uses_count FROM promo_codes WHERE id=1").fetchone()[0]==1
  assert c.execute("SELECT count(*) FROM promo_uses WHERE code_id=1").fetchone()[0]==1
 # Replacing a lock deactivates the previous active promise atomically.
 old=store.replace_rate_lock(user_id=8,currency="LTC",locked_rate=100,fee_rub=100,locked_until=future)
 new=store.replace_rate_lock(user_id=8,currency="LTC",locked_rate=101,fee_rub=100,locked_until=future)
 assert store.active_rate_lock(8,"LTC")["lock_id"]==new
 with sqlite3.connect(path) as c:
  assert c.execute("SELECT used FROM rate_locks WHERE id=?",(old,)).fetchone()[0]==1
  c.execute("CREATE TRIGGER fail_order BEFORE INSERT ON orders WHEN NEW.user_id=9 "
            "BEGIN SELECT RAISE(ABORT,'fault'); END")
 fault_lock=store.replace_rate_lock(user_id=9,currency="BTC",locked_rate=10,fee_rub=1,locked_until=future)
 try:
  store.create_order(user_id=9,username="u",currency="BTC",rub_amount=1,destination="x",
   network=None,preferred_rate=10,preferred_crypto_amount=.1,fallback_rate=11,
   fallback_crypto_amount=.09,lock_id=fault_lock)
  raise AssertionError("fault did not abort")
 except sqlite3.IntegrityError: pass
 assert store.active_rate_lock(9,"BTC")["lock_id"]==fault_lock
print("SQLite bot order/rate-lock repository checks: OK")
