import sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"relay"))
from repositories.gift_store import SQLiteGiftStore,GiftCodeConflict
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/"g.db")
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE orders(order_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,currency TEXT,rub_amount REAL,crypto_address TEXT,status TEXT,agreed_rate REAL,agreed_crypto_amount REAL,agreed_at TEXT);CREATE TABLE gift_vouchers(id INTEGER PRIMARY KEY AUTOINCREMENT,sender_id INTEGER,currency TEXT,rub_amount REAL,code TEXT UNIQUE,status TEXT DEFAULT 'pending',order_id INTEGER,recipient_id INTEGER,recipient_address TEXT,claimed_at TEXT);""")
 s=SQLiteGiftStore(p);assert not s.code_exists('GIFT') and s.card(999) is None;g=s.issue(sender_id=1,currency="BTC",rub_amount=100,destination="placeholder",code="GIFT",agreed_rate=10,agreed_crypto_amount=10);assert s.code_exists('GIFT') and s.card(g['gift_id'])==('BTC',100.0,'GIFT')
 try:s.issue(sender_id=1,currency="BTC",rub_amount=100,destination="x",code="GIFT",agreed_rate=10,agreed_crypto_amount=10);raise AssertionError()
 except GiftCodeConflict:pass
 with sqlite3.connect(p) as c:c.execute("UPDATE gift_vouchers SET status='paid' WHERE id=?",(g["gift_id"],));c.commit()
 assert s.redeem(gift_id=g["gift_id"],recipient_id=2,destination="dest",agreed_rate=11,agreed_crypto_amount=9)["action"]=="redeemed"
 assert s.redeem(gift_id=g["gift_id"],recipient_id=3,destination="dest2",agreed_rate=11,agreed_crypto_amount=9)["action"]=="not_redeemable"
 with sqlite3.connect(p) as c:assert c.execute("SELECT count(*) FROM orders").fetchone()[0]==2
print("SQLite gift repository checks: OK")
