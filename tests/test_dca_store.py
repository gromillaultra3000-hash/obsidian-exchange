import sqlite3,sys,tempfile
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.dca_store import SQLiteDcaStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'d.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE dca_schedules(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,currency TEXT,rub_amount REAL,crypto_address TEXT,interval_days INTEGER,next_run TEXT,runs_total INTEGER DEFAULT 0,status TEXT DEFAULT 'active');CREATE TABLE orders(order_id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,username TEXT,currency TEXT,rub_amount REAL,crypto_address TEXT,status TEXT,agreed_rate REAL,agreed_crypto_amount REAL,agreed_at TEXT);""")
 s=SQLiteDcaStore(p);past=datetime.now(timezone.utc)-timedelta(minutes=1);did=s.create(user_id=1,currency='BTC',rub_amount=100,destination='dest',interval_days=7,next_run=past);listed=s.for_user(1);assert len(listed)==1 and listed[0][0]==did and listed[0][1]=='BTC' and isinstance(listed[0][4],str);row=s.due()[0];future=datetime.now(timezone.utc)+timedelta(days=7)
 assert s.run_due(schedule_id=did,expected_next_run=row['next_run'],destination='dest',agreed_rate=10,agreed_crypto_amount=10,next_run=future)['action']=='created'
 assert s.run_due(schedule_id=did,expected_next_run=row['next_run'],destination='dest',agreed_rate=10,agreed_crypto_amount=10,next_run=future)['action']=='lost_race'
 with sqlite3.connect(p) as c:assert c.execute('SELECT count(*) FROM orders').fetchone()[0]==1 and c.execute('SELECT runs_total FROM dca_schedules').fetchone()[0]==1
print('SQLite DCA repository checks: OK')
