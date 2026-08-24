import sqlite3,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.wallet_store import SQLiteWalletStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'w.db')
 with sqlite3.connect(p) as c:c.executescript("CREATE TABLE wallet_links(user_id INTEGER NOT NULL,chain TEXT NOT NULL,address TEXT NOT NULL,verified_at TEXT NOT NULL,PRIMARY KEY(user_id,chain));CREATE TABLE wallet_send_intents(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL,chain TEXT NOT NULL,sell_id INTEGER NOT NULL,from_address TEXT NOT NULL,to_address TEXT NOT NULL,amount REAL NOT NULL,marker TEXT NOT NULL,created_at TEXT NOT NULL,signed_at TEXT);")
 s=SQLiteWalletStore(p);s.remember_link(user_id=1,chain='TON',address='a',verified_at='2026-01-01T00:00:00+00:00');s.remember_link(user_id=1,chain='TON',address='b',verified_at='2026-01-02T00:00:00+00:00');assert s.links_for(1)[0]['address']=='b';iid=s.remember_intent(user_id=1,chain='TON',sell_id=2,from_address='b',to_address='c',amount=1,marker='m',created_at='2026-01-01 00:00:00');assert iid and s.mark_signed(user_id=1,sell_id=2,signed_at='2026-01-01 00:01:00') and not s.mark_signed(user_id=1,sell_id=2,signed_at='x');assert s.intents_for(2)[0]['signed_at'];assert s.forget_links(user_id=1)==1
print('SQLite wallet repository checks: OK')
