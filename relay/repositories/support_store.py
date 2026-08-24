"""Atomic support-ticket creation and replies shared by web and Telegram."""
from __future__ import annotations
import os
from core import db_runtime

class SQLiteSupportStore:
 def __init__(self,path:str,*,timeout:float=5):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def create(self,*,subject:str,message:str,user_id:int|None=None,username:str|None=None,web_user_id:int=0):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');q=c.execute("INSERT INTO support_tickets(user_id,username,web_user_id,subject,status) VALUES(?,?,?,?,'open')",(user_id,username,web_user_id,subject));tid=int(q.lastrowid)
   c.execute("INSERT INTO support_messages(ticket_id,sender,message) VALUES(?,'user',?)",(tid,message));c.commit();return tid
 def user_reply(self,*,ticket_id:int,message:str,user_id:int|None=None,web_user_id:int|None=None):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE')
   if web_user_id is not None:r=c.execute("SELECT subject,username FROM support_tickets WHERE id=? AND web_user_id=?",(ticket_id,web_user_id)).fetchone()
   else:r=c.execute("SELECT subject,username FROM support_tickets WHERE id=? AND user_id=?",(ticket_id,user_id)).fetchone()
   if not r:return None
   c.execute("INSERT INTO support_messages(ticket_id,sender,message) VALUES(?,'user',?)",(ticket_id,message));c.execute("UPDATE support_tickets SET status='open',updated_at=CURRENT_TIMESTAMP WHERE id=?",(ticket_id,));c.commit();return {'subject':r[0],'username':r[1]}
 def admin_reply(self,*,ticket_id:int,message:str):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT user_id,subject FROM support_tickets WHERE id=?",(ticket_id,)).fetchone()
   if not r:return None
   c.execute("INSERT INTO support_messages(ticket_id,sender,message) VALUES(?,'admin',?)",(ticket_id,message));c.execute("UPDATE support_tickets SET status='answered',updated_at=CURRENT_TIMESTAMP WHERE id=?",(ticket_id,));c.commit();return {'user_id':r[0],'subject':r[1]}
 def open_count_for_web_user(self,web_user_id:int):
  with self._c() as c:return int(c.execute("SELECT COUNT(id) FROM support_tickets WHERE web_user_id=? AND status!='closed'",(web_user_id,)).fetchone()[0])
 def list_for_web_user(self,web_user_id:int):
  with self._c() as c:
   rows=c.execute("SELECT id,subject,status,created_at,updated_at FROM support_tickets WHERE web_user_id=? ORDER BY updated_at DESC,id DESC LIMIT 100",(web_user_id,)).fetchall()
  keys=('id','subject','status','created_at','updated_at');return [dict(zip(keys,r)) for r in rows]
 def thread_for_web_user(self,*,ticket_id:int,web_user_id:int):
  with self._c() as c:
   ticket=c.execute("SELECT id,subject,status FROM support_tickets WHERE id=? AND web_user_id=?",(ticket_id,web_user_id)).fetchone()
   if not ticket:return None
   rows=c.execute("SELECT sender,message,created_at FROM (SELECT id,sender,message,created_at FROM support_messages WHERE ticket_id=? ORDER BY created_at DESC,id DESC LIMIT 500) recent ORDER BY created_at ASC,id ASC",(ticket_id,)).fetchall()
  keys=('sender','message','created_at');return {'ticket':dict(zip(('id','subject','status'),ticket)),'messages':[dict(zip(keys,r)) for r in rows]}
 def exists_for_web_user(self,*,ticket_id:int,web_user_id:int):
  with self._c() as c:return c.execute("SELECT 1 FROM support_tickets WHERE id=? AND web_user_id=?",(ticket_id,web_user_id)).fetchone() is not None
 def list_for_telegram_user(self,user_id:int,limit:int=5):
  with self._c() as c:return c.execute("SELECT id,subject,status,updated_at FROM support_tickets WHERE user_id=? ORDER BY updated_at DESC LIMIT ?",(int(user_id),max(1,min(int(limit),100)))).fetchall()
 def thread_for_telegram_user(self,*,ticket_id:int,user_id:int):
  with self._c() as c:
   ticket=c.execute("SELECT subject,status FROM support_tickets WHERE id=? AND user_id=?",(int(ticket_id),int(user_id))).fetchone()
   if not ticket:return None
   messages=c.execute("SELECT sender,message,created_at FROM (SELECT id,sender,message,created_at FROM support_messages WHERE ticket_id=? ORDER BY id DESC LIMIT 500) recent ORDER BY id",(int(ticket_id),)).fetchall()
  return {'subject':ticket[0],'status':ticket[1],'messages':messages}
 def staff_open_tickets(self,limit:int=20):
  with self._c() as c:return c.execute("SELECT id,user_id,username,subject,status,updated_at FROM support_tickets WHERE status IN ('open','answered') ORDER BY updated_at DESC LIMIT ?",(max(1,min(int(limit),100)),)).fetchall()
 def staff_new_tickets(self,limit:int=10):
  with self._c() as c:return c.execute("SELECT id,username,user_id,subject,updated_at FROM support_tickets WHERE status='open' ORDER BY updated_at ASC LIMIT ?",(max(1,min(int(limit),100)),)).fetchall()
 def open_count(self):
  with self._c() as c:return int(c.execute("SELECT COUNT(*) FROM support_tickets WHERE status IN ('open','answered')").fetchone()[0])
 def open_count_for_telegram_user(self,user_id:int):
  with self._c() as c:return int(c.execute("SELECT COUNT(*) FROM support_tickets WHERE user_id=? AND status='open'",(int(user_id),)).fetchone()[0])

class PostgresSupportStore:
 def __init__(self,dsn:str):self.dsn=dsn
 def _c(self):
  import psycopg
  from psycopg.rows import dict_row
  return psycopg.connect(self.dsn,row_factory=dict_row)
 def create(self,*,subject:str,message:str,user_id:int|None=None,username:str|None=None,web_user_id:int=0):
  with self._c() as c,c.cursor() as q:
   q.execute("INSERT INTO support_tickets(user_id,username,web_user_id,subject,status) VALUES(%s,%s,%s,%s,'open') RETURNING id",(user_id,username,web_user_id,subject));tid=int(q.fetchone()['id']);q.execute("INSERT INTO support_messages(ticket_id,sender,message) VALUES(%s,'user',%s)",(tid,message));return tid
 def user_reply(self,*,ticket_id:int,message:str,user_id:int|None=None,web_user_id:int|None=None):
  with self._c() as c,c.cursor() as q:
   if web_user_id is not None:q.execute("SELECT subject,username FROM support_tickets WHERE id=%s AND web_user_id=%s FOR UPDATE",(ticket_id,web_user_id))
   else:q.execute("SELECT subject,username FROM support_tickets WHERE id=%s AND user_id=%s FOR UPDATE",(ticket_id,user_id))
   r=q.fetchone()
   if not r:return None
   q.execute("INSERT INTO support_messages(ticket_id,sender,message) VALUES(%s,'user',%s)",(ticket_id,message));q.execute("UPDATE support_tickets SET status='open',updated_at=now() WHERE id=%s",(ticket_id,));return dict(r)
 def admin_reply(self,*,ticket_id:int,message:str):
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT user_id,subject FROM support_tickets WHERE id=%s FOR UPDATE",(ticket_id,));r=q.fetchone()
   if not r:return None
   q.execute("INSERT INTO support_messages(ticket_id,sender,message) VALUES(%s,'admin',%s)",(ticket_id,message));q.execute("UPDATE support_tickets SET status='answered',updated_at=now() WHERE id=%s",(ticket_id,));return dict(r)
 def open_count_for_web_user(self,web_user_id:int):
  with self._c() as c:return int(c.execute("SELECT COUNT(id) AS count FROM support_tickets WHERE web_user_id=%s AND status!='closed'",(web_user_id,)).fetchone()['count'])
 def list_for_web_user(self,web_user_id:int):
  with self._c() as c:return [dict(r) for r in c.execute("SELECT id,subject,status,created_at,updated_at FROM support_tickets WHERE web_user_id=%s ORDER BY updated_at DESC,id DESC LIMIT 100",(web_user_id,)).fetchall()]
 def thread_for_web_user(self,*,ticket_id:int,web_user_id:int):
  with self._c() as c:
   ticket=c.execute("SELECT id,subject,status FROM support_tickets WHERE id=%s AND web_user_id=%s",(ticket_id,web_user_id)).fetchone()
   if not ticket:return None
   rows=c.execute("SELECT sender,message,created_at FROM (SELECT id,sender,message,created_at FROM support_messages WHERE ticket_id=%s ORDER BY created_at DESC,id DESC LIMIT 500) recent ORDER BY created_at ASC,id ASC",(ticket_id,)).fetchall()
  return {'ticket':dict(ticket),'messages':[dict(r) for r in rows]}
 def exists_for_web_user(self,*,ticket_id:int,web_user_id:int):
  with self._c() as c:return c.execute("SELECT 1 FROM support_tickets WHERE id=%s AND web_user_id=%s",(ticket_id,web_user_id)).fetchone() is not None
 def list_for_telegram_user(self,user_id:int,limit:int=5):
  with self._c() as c:
   rows=c.execute("SELECT id,subject,status,updated_at FROM support_tickets WHERE user_id=%s ORDER BY updated_at DESC LIMIT %s",(int(user_id),max(1,min(int(limit),100)))).fetchall()
  return [(r['id'],r['subject'],r['status'],str(r['updated_at'])) for r in rows]
 def thread_for_telegram_user(self,*,ticket_id:int,user_id:int):
  with self._c() as c:
   ticket=c.execute("SELECT subject,status FROM support_tickets WHERE id=%s AND user_id=%s",(int(ticket_id),int(user_id))).fetchone()
   if not ticket:return None
   rows=c.execute("SELECT sender,message,created_at FROM (SELECT id,sender,message,created_at FROM support_messages WHERE ticket_id=%s ORDER BY id DESC LIMIT 500) recent ORDER BY id",(int(ticket_id),)).fetchall()
  return {'subject':ticket['subject'],'status':ticket['status'],'messages':[(r['sender'],r['message'],str(r['created_at'])) for r in rows]}
 def staff_open_tickets(self,limit:int=20):
  with self._c() as c:
   rows=c.execute("SELECT id,user_id,username,subject,status,updated_at FROM support_tickets WHERE status IN ('open','answered') ORDER BY updated_at DESC LIMIT %s",(max(1,min(int(limit),100)),)).fetchall()
  return [(r['id'],r['user_id'],r['username'],r['subject'],r['status'],str(r['updated_at'])) for r in rows]
 def staff_new_tickets(self,limit:int=10):
  with self._c() as c:
   rows=c.execute("SELECT id,username,user_id,subject,updated_at FROM support_tickets WHERE status='open' ORDER BY updated_at ASC LIMIT %s",(max(1,min(int(limit),100)),)).fetchall()
  return [(r['id'],r['username'],r['user_id'],r['subject'],str(r['updated_at'])) for r in rows]
 def open_count(self):
  with self._c() as c:return int(c.execute("SELECT COUNT(*) AS count FROM support_tickets WHERE status IN ('open','answered')").fetchone()['count'])
 def open_count_for_telegram_user(self,user_id:int):
  with self._c() as c:return int(c.execute("SELECT COUNT(*) AS count FROM support_tickets WHERE user_id=%s AND status='open'",(int(user_id),)).fetchone()['count'])

def from_environment(*,sqlite_path:str):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteSupportStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('SUPPORT_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_support_store_not_enabled')
 return PostgresSupportStore(url)
