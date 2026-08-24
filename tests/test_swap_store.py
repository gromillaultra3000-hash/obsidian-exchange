import sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.swap_store import SQLiteSwapStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'s.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE swap_sessions(id INTEGER PRIMARY KEY AUTOINCREMENT,session_token TEXT UNIQUE,user_id INTEGER,coin_from TEXT,coin_to TEXT,amount_from REAL,address_to TEXT,trocador_id TEXT,trocador_url TEXT,status TEXT,web_user_id INTEGER,provider TEXT,deposit_address TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
 s=SQLiteSwapStore(p);s.create(token='t',user_id=1,coin_from='BTC',coin_to='ETH',amount_from=1,address_to='a',external_id='x',external_url='u',status='waiting',provider='swapuz',deposit_address='d');rows=s.unfinished(('finished','failed'));assert len(rows)==1 and rows[0][0]=='t' and rows[0][7]==1;assert s.unfinished(())==[];assert s.transition(token='t',expected_status='waiting',new_status='confirming');assert not s.transition(token='t',expected_status='waiting',new_status='failed')
 s.create(token='web-old',user_id=-41,web_user_id=41,coin_from='BTC',coin_to='LTC',amount_from=2,address_to='wa',external_id='wx1',external_url='wu1',status='waiting',provider='trocador',deposit_address='wd1');s.create(token='web-new',user_id=700,web_user_id=0,coin_from='ETH',coin_to='BTC',amount_from=3,address_to='wb',external_id='wx2',external_url='wu2',status='confirming',provider='swapuz',deposit_address='wd2');s.create(token='foreign',user_id=701,web_user_id=42,coin_from='TON',coin_to='BTC',amount_from=4,address_to='wc',external_id='wx3',external_url='wu3',status='waiting',provider='swapuz',deposit_address='wd3')
 with sqlite3.connect(p) as c:c.execute("UPDATE swap_sessions SET created_at='2026-01-01 00:00:00' WHERE session_token IN('web-old','web-new')");c.commit()
 assert [x['token'] for x in s.swaps_for_web_user(web_user_id=41,user_id=700)]==['web-new','web-old'];assert [x['token'] for x in s.swaps_for_web_user(web_user_id=41,user_id=None)]==['web-old'];assert s.get_by_token('foreign')['external_id']=='wx3';assert s.get_by_external_id('wx2')['session_token']=='web-new';assert s.get_by_token('missing') is None
 with sqlite3.connect(p) as c:assert c.execute('SELECT status FROM swap_sessions').fetchone()[0]=='confirming'
print('SQLite swap repository checks: OK')
