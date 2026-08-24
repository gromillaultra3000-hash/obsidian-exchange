import ast,sqlite3,sys,tempfile
from datetime import datetime,timedelta
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.promo_admin_store import SQLitePromoAdminStore
bot_source=(ROOT/'bot/main_bot.py').read_text('utf-8');bot_tree=ast.parse(bot_source)
for name,call in [('check_promo_code','validate_for_user'),('cmd_promos','active')]:
 node=next(x for x in ast.walk(bot_tree) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name);source=ast.get_source_segment(bot_source,node);assert f'_promo_admin.{call}(' in source;assert 'promo_codes' not in source and 'promo_uses' not in source
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'p.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE promo_codes(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE COLLATE NOCASE,discount_percent REAL,max_uses INTEGER,uses_count INTEGER DEFAULT 0,valid_until TEXT,is_active INTEGER DEFAULT 1,created_at TEXT DEFAULT CURRENT_TIMESTAMP);CREATE TABLE promo_uses(code_id INTEGER,user_id INTEGER,order_id INTEGER,PRIMARY KEY(code_id,user_id));CREATE TABLE sent_notifications(order_id INTEGER,event TEXT,PRIMARY KEY(order_id,event));""")
 s=SQLitePromoAdminStore(p);aid=s.create(code='A',discount=1,max_uses=2,valid_until=datetime.now()+timedelta(days=1));assert s.issue_winback(order_id=1,code='B',discount=2,valid_hours=3);assert s.issue_winback(order_id=1,code='C',discount=2,valid_hours=3) is None
 assert s.validate_for_user(code='a',user_id=7)=={'code_id':aid,'discount':1.0};assert s.active(limit=1)[0][0]=='B'
 with sqlite3.connect(p) as c:c.execute("INSERT INTO promo_uses VALUES(?,?,?)",(aid,7,1));c.execute("UPDATE promo_codes SET uses_count=max_uses WHERE id=?",(aid,));c.commit()
 assert s.validate_for_user(code='A',user_id=7) is None
print('SQLite promo-admin repository checks: OK')
