import sqlite3,tempfile,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.alert_store import SQLiteAlertStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'a.db');s=SQLiteAlertStore(p)
 try:s.should_send('missing',60);assert False
 except sqlite3.OperationalError:pass
 with sqlite3.connect(p) as c:c.executescript("CREATE TABLE alert_throttle(key TEXT PRIMARY KEY,last_sent TEXT NOT NULL);CREATE TABLE alert_watermark(key TEXT PRIMARY KEY,value INTEGER NOT NULL);")
 assert s.should_send('x',60) and not s.should_send('x',60);assert s.high_water('q',2) and not s.high_water('q',1) and s.high_water('q',3);assert isinstance(s.cleanup(30),int)
print('SQLite alert repository checks: OK')
