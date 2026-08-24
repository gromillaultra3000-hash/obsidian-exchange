import sqlite3,sys,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.limit_order_store import SQLiteLimitOrderStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'l.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE limit_orders(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,currency TEXT,target_rate REAL,direction TEXT,rub_amount REAL,crypto_address TEXT,payment_method TEXT,status TEXT DEFAULT 'active',expires_at TEXT,triggered_at TEXT,order_id INTEGER);CREATE TABLE orders(order_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,currency TEXT,rub_amount REAL,crypto_address TEXT,status TEXT,username TEXT,agreed_rate REAL,agreed_crypto_amount REAL,agreed_at TEXT);""")
 s=SQLiteLimitOrderStore(p);exp=datetime.now(timezone.utc)+timedelta(days=1);lid=s.create(user_id=1,currency='BTC',target_rate=10,direction='below',rub_amount=100,destination='d',payment_method='sbp',expires_at=exp);listed=s.for_user(1);assert len(listed)==1 and listed[0][0]==lid and listed[0][2]=='below' and isinstance(listed[0][6],str);row=s.active()[0]
 assert s.trigger(ident=lid,expected_expires_at=row['expires_at'],destination='d',agreed_rate=10,agreed_crypto_amount=10)['action']=='triggered'
 assert s.trigger(ident=lid,expected_expires_at=row['expires_at'],destination='d',agreed_rate=10,agreed_crypto_amount=10)['action']=='lost_race'
 with sqlite3.connect(p) as c:assert c.execute('SELECT count(*) FROM orders').fetchone()[0]==1
print('SQLite limit-order repository checks: OK')
