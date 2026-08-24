import sqlite3,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.ops_store import SQLiteOpsStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'o.db')
 with sqlite3.connect(p) as c:c.executescript("CREATE TABLE orders(order_id INTEGER PRIMARY KEY,status TEXT,rub_amount REAL,crypto_address TEXT,currency TEXT,updated_at TEXT);CREATE TABLE system_flags(key TEXT PRIMARY KEY,value TEXT,updated_at TEXT);CREATE TABLE audit_log(id INTEGER PRIMARY KEY AUTOINCREMENT,event TEXT NOT NULL,details TEXT NOT NULL,created_at TEXT DEFAULT CURRENT_TIMESTAMP);INSERT INTO orders VALUES(1,'sent',100,'addr','BTC',datetime('now','-30 minutes'));INSERT INTO orders VALUES(2,'sent',200,'addr2','LTC',datetime('now','-2 hours'));")
 s=SQLiteOpsStore(p);s.set_flags({'payout_frozen':'1','payout_frozen_reason':'x'});assert s.get_flag('payout_frozen')=='1';s.set_flags({'payout_frozen':'0','payout_frozen_reason':''});assert s.get_flag('payout_frozen_reason')=='';s.audit(event='e',details='d');s.audit(event='old',details='d')
 with sqlite3.connect(p) as c:c.execute("UPDATE audit_log SET created_at=datetime('now','-91 days') WHERE event='old'")
 assert s.cleanup_audit(90)==1
 with sqlite3.connect(p) as c:assert c.execute("SELECT event FROM audit_log").fetchall()==[('e',)]
 assert s.payout_totals(1)==(100.0,1);assert s.payout_totals(24)==(300.0,2);assert s.recent_payout_destinations(1)==[('addr','BTC')]
print('SQLite ops repository checks: OK')
