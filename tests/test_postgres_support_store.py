import os,sys,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres support store: skipped');raise SystemExit(0)
from repositories.support_store import PostgresSupportStore
s=PostgresSupportStore(dsn);tid=s.create(user_id=7,username='u',subject='x',message='first');assert s.user_reply(ticket_id=tid,user_id=8,message='bad') is None;assert s.user_reply(ticket_id=tid,user_id=7,message='next')['subject']=='x';assert s.admin_reply(ticket_id=tid,message='answer')['user_id']==7
wid=900000000+time.time_ns()%100000000;web_old=s.create(web_user_id=wid,subject='old',message='first');web_new=s.create(web_user_id=wid,subject='new',message='same-time-1');s.user_reply(ticket_id=web_new,web_user_id=wid,message='same-time-2');foreign=s.create(web_user_id=wid+1,subject='foreign',message='secret')
with s._c() as c:c.execute("UPDATE support_tickets SET status='closed',updated_at='2026-01-01 00:00:00' WHERE id=%s",(web_old,));c.execute("UPDATE support_tickets SET updated_at='2026-01-02 00:00:00' WHERE id=%s",(web_new,));c.execute("UPDATE support_messages SET created_at='2026-01-02 00:00:00' WHERE ticket_id=%s",(web_new,))
assert s.open_count_for_web_user(wid)==1;assert [x['id'] for x in s.list_for_web_user(wid)]==[web_new,web_old];thread=s.thread_for_web_user(ticket_id=web_new,web_user_id=wid);assert [x['message'] for x in thread['messages']]==['same-time-1','same-time-2'];assert s.thread_for_web_user(ticket_id=foreign,web_user_id=wid) is None;assert s.exists_for_web_user(ticket_id=web_new,web_user_id=wid);assert not s.exists_for_web_user(ticket_id=foreign,web_user_id=wid)
uid=800000000+time.time_ns()%100000000;telegram_old=s.create(user_id=uid,username='u',subject='older',message='one');telegram_new=s.create(user_id=uid,username='u',subject='newer',message='first');s.user_reply(ticket_id=telegram_new,user_id=uid,message='second');telegram_foreign=s.create(user_id=uid+1,username='other',subject='private',message='secret')
with s._c() as c:c.execute("UPDATE support_tickets SET updated_at='2026-02-01 00:00:00+00' WHERE id=%s",(telegram_old,));c.execute("UPDATE support_tickets SET updated_at='2026-02-02 00:00:00+00' WHERE id=%s",(telegram_new,))
assert [x[0] for x in s.list_for_telegram_user(uid,limit=2)]==[telegram_new,telegram_old];thread=s.thread_for_telegram_user(ticket_id=telegram_new,user_id=uid);assert [x[1] for x in thread['messages']]==['first','second'];assert s.thread_for_telegram_user(ticket_id=telegram_foreign,user_id=uid) is None
assert s.open_count_for_telegram_user(uid)==2;assert s.open_count()>=3;assert telegram_new in [x[0] for x in s.staff_open_tickets(limit=100)]
assert telegram_old in [x[0] for x in s.staff_new_tickets(limit=100)]
print('PostgreSQL support repository checks: OK')
