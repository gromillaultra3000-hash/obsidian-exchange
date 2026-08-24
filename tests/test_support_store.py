import ast,sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.support_store import SQLiteSupportStore
bot_source=(ROOT/'bot/main_bot.py').read_text('utf-8');bot_tree=ast.parse(bot_source)
for name,call in [('menu_support_new','list_for_telegram_user'),('ticket_view','thread_for_telegram_user'),('cmd_tickets','staff_open_tickets')]:
 node=next(x for x in ast.walk(bot_tree) if isinstance(x,(ast.FunctionDef,ast.AsyncFunctionDef)) and x.name==name);source=ast.get_source_segment(bot_source,node);assert f'_support_store.{call}(' in source;assert 'support_tickets' not in source and 'support_messages' not in source
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'s.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE support_tickets(id INTEGER PRIMARY KEY AUTOINCREMENT,web_user_id INTEGER DEFAULT 0,user_id INTEGER,username TEXT,subject TEXT,status TEXT DEFAULT 'open',created_at TEXT DEFAULT CURRENT_TIMESTAMP,updated_at TEXT DEFAULT CURRENT_TIMESTAMP);CREATE TABLE support_messages(id INTEGER PRIMARY KEY AUTOINCREMENT,ticket_id INTEGER,sender TEXT,message TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);""")
 s=SQLiteSupportStore(p);tid=s.create(user_id=7,username='u',subject='x',message='first');assert s.user_reply(ticket_id=tid,user_id=8,message='bad') is None;assert s.user_reply(ticket_id=tid,user_id=7,message='next')['subject']=='x';assert s.admin_reply(ticket_id=tid,message='answer')['user_id']==7
 web_old=s.create(web_user_id=41,subject='old',message='first');web_new=s.create(web_user_id=41,subject='new',message='same-time-1');s.user_reply(ticket_id=web_new,web_user_id=41,message='same-time-2');foreign=s.create(web_user_id=42,subject='foreign',message='secret')
 with sqlite3.connect(p) as c:c.execute("UPDATE support_tickets SET status='closed',updated_at='2026-01-01 00:00:00' WHERE id=?",(web_old,));c.execute("UPDATE support_tickets SET updated_at='2026-01-02 00:00:00' WHERE id=?",(web_new,));c.execute("UPDATE support_messages SET created_at='2026-01-02 00:00:00' WHERE ticket_id=?",(web_new,));c.commit()
 assert s.open_count_for_web_user(41)==1;assert [x['id'] for x in s.list_for_web_user(41)]==[web_new,web_old];thread=s.thread_for_web_user(ticket_id=web_new,web_user_id=41);assert [x['message'] for x in thread['messages']]==['same-time-1','same-time-2'];assert s.thread_for_web_user(ticket_id=foreign,web_user_id=41) is None;assert s.exists_for_web_user(ticket_id=web_new,web_user_id=41);assert not s.exists_for_web_user(ticket_id=foreign,web_user_id=41)
 with sqlite3.connect(p) as c:assert c.execute('SELECT status FROM support_tickets WHERE id=?',(tid,)).fetchone()[0]=='answered' and c.execute('SELECT count(*) FROM support_messages WHERE ticket_id=?',(tid,)).fetchone()[0]==3
 telegram_old=s.create(user_id=77,username='u',subject='older',message='one');telegram_new=s.create(user_id=77,username='u',subject='newer',message='first');s.user_reply(ticket_id=telegram_new,user_id=77,message='second');telegram_foreign=s.create(user_id=78,username='other',subject='private',message='secret')
 with sqlite3.connect(p) as c:c.execute("UPDATE support_tickets SET updated_at='2026-02-01 00:00:00' WHERE id=?",(telegram_old,));c.execute("UPDATE support_tickets SET updated_at='2026-02-02 00:00:00' WHERE id=?",(telegram_new,));c.commit()
 assert [x[0] for x in s.list_for_telegram_user(77,limit=2)]==[telegram_new,telegram_old]
 thread=s.thread_for_telegram_user(ticket_id=telegram_new,user_id=77);assert [x[1] for x in thread['messages']]==['first','second'];assert s.thread_for_telegram_user(ticket_id=telegram_foreign,user_id=77) is None
 assert s.open_count_for_telegram_user(77)==2;assert s.open_count()>=3
 assert telegram_new in [x[0] for x in s.staff_open_tickets(limit=20)]
 assert telegram_old in [x[0] for x in s.staff_new_tickets(limit=20)]
print('SQLite support repository checks: OK')
