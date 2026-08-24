"""Customer engagement, staff audit and loyalty persistence."""
from __future__ import annotations
import os
from core import db_runtime

def _audit_fields(uid,action,target_id,details):
 uid=int(uid)
 if uid<=0:raise ValueError('invalid_audit_actor')
 action=str(action or '').strip()
 if not action or len(action)>80:raise ValueError('invalid_audit_action')
 target=int(target_id) if target_id is not None else None
 detail=None if details is None else str(details)
 if detail is not None and len(detail)>500:raise ValueError('invalid_audit_details')
 return uid,action,target,detail


class SQLiteEngagementStore:
 def __init__(self,path,*,timeout=10):self.path,self.timeout=path,timeout
 def _c(self):return db_runtime.sqlite_connect(self.path,timeout=self.timeout)
 def log_action(self,uid,action,target_id=None,details=None):
  uid,action,target_id,details=_audit_fields(uid,action,target_id,details)
  with self._c() as c:c.execute("INSERT INTO admin_log(admin_id,action,target_id,details) VALUES(?,?,?,?)",(uid,action,target_id,details));c.commit()
 def vip_total(self,user_id):
  with self._c() as c:r=c.execute("SELECT total_rub FROM user_vip_volume WHERE user_id=?",(user_id,)).fetchone();return float(r[0] or 0) if r else 0
 def add_vip(self,user_id,amount):
  with self._c() as c:c.execute("INSERT INTO user_vip_volume(user_id,total_rub,updated_at) VALUES(?,?,CURRENT_TIMESTAMP) ON CONFLICT(user_id) DO UPDATE SET total_rub=total_rub+excluded.total_rub,updated_at=CURRENT_TIMESTAMP",(user_id,amount));c.commit()
 def toggle_rate(self,user_id):
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE')
   c.execute("INSERT OR IGNORE INTO rate_subscriptions(user_id) VALUES(?)",(user_id,))
   r=c.execute("UPDATE rate_subscriptions SET enabled=NOT enabled WHERE user_id=? RETURNING enabled",(user_id,)).fetchone()
   c.commit();return bool(r[0])
 def rate_enabled(self,user_id):
  with self._c() as c:r=c.execute("SELECT enabled FROM rate_subscriptions WHERE user_id=?",(user_id,)).fetchone();return bool(r and r[0])
 def subscribers(self):
  rows=[];after=0
  with self._c() as c:
   while True:
    page=c.execute("SELECT user_id,last_notified,last_btc,last_ltc,last_usdt FROM rate_subscriptions WHERE enabled=1 AND user_id>? ORDER BY user_id LIMIT 500",(after,)).fetchall()
    if not page:break
    rows.extend(page);after=int(page[-1][0])
  return rows
 def update_rates(self,user_id,notified,btc,ltc,usdt):
  with self._c() as c:c.execute("UPDATE rate_subscriptions SET last_notified=?,last_btc=?,last_ltc=?,last_usdt=? WHERE user_id=?",(notified,btc,ltc,usdt,user_id));c.commit()
 def disable_rates(self,user_id):
  with self._c() as c:c.execute("UPDATE rate_subscriptions SET enabled=0 WHERE user_id=?",(user_id,));c.commit()
 def review_summary(self):
  with self._c() as c:r=c.execute("SELECT COUNT(*),AVG(rating) FROM reviews WHERE status='published'").fetchone();return int(r[0]),float(r[1] or 0)
 def ensure_review(self,order_id,user_id):
  with self._c() as c:c.execute("INSERT OR IGNORE INTO reviews(order_id,user_id,status) VALUES(?,?,'pending_rating')",(order_id,user_id));c.commit()
 def rate_review(self,order_id,user_id,rating):
  with self._c() as c:q=c.execute("UPDATE reviews SET rating=?,status='pending_comment' WHERE order_id=? AND user_id=? AND status='pending_rating' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=?)",(rating,order_id,user_id,user_id));c.commit();return q.rowcount==1
 def comment_review(self,order_id,user_id,comment):
  with self._c() as c:q=c.execute("UPDATE reviews SET comment=? WHERE order_id=? AND user_id=? AND status='pending_comment' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=?)",(comment,order_id,user_id,user_id));c.commit();return q.rowcount==1
 def finalize_review(self,order_id,user_id):
  with self._c() as c:
   r=c.execute("SELECT user_id,rating,comment FROM reviews WHERE order_id=? AND user_id=? AND status='pending_comment' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=?)",(order_id,user_id,user_id)).fetchone()
   if not r:return None
   status='published' if r[1] and r[1]>=4 else 'admin_review';q=c.execute("UPDATE reviews SET status=? WHERE order_id=? AND user_id=? AND status='pending_comment' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=?)",(status,order_id,user_id,user_id));c.commit();return {'user_id':r[0],'rating':r[1],'comment':r[2],'status':status} if q.rowcount==1 else None
 def referral_bonus(self,user_id,date_from=None,date_to=None):
  if (date_from is None) != (date_to is None):raise ValueError('referral_bonus_date_range_required')
  if date_from is None and user_id is None:raise ValueError('referral_bonus_user_required')
  if date_from is not None and user_id is not None:raise ValueError('referral_bonus_period_is_operator_aggregate')
  with self._c() as c:
   if date_from is None:r=c.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_bonuses WHERE referrer_id=?",(user_id,)).fetchone()
   else:r=c.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_bonuses WHERE created_at>=? AND created_at<?",(date_from,date_to+'T23:59:59.999999')).fetchone()
   return float(r[0] or 0)
 def referral_stats(self,user_id):
  with self._c() as c:
   r=c.execute("SELECT COUNT(referred_id),COALESCE(SUM(total_bonus_btc),0) FROM referrals WHERE referrer_id=?",(int(user_id),)).fetchone()
   active=c.execute("SELECT COUNT(DISTINCT r.referred_id) FROM referrals r JOIN orders o ON o.user_id=r.referred_id AND o.status='sent' WHERE r.referrer_id=?",(int(user_id),)).fetchone()[0]
   return {'referrals':int(r[0] or 0),'active':int(active or 0),'total_bonus_btc':float(r[1] or 0)}
 def credit_referral_bonus(self,user_id,bonus_btc):
  amount=float(bonus_btc)
  if amount<=0:return None
  with self._c() as c:
   c.execute('BEGIN IMMEDIATE');r=c.execute("SELECT referrer_id FROM referrals WHERE referred_id=? ORDER BY referrer_id LIMIT 1",(int(user_id),)).fetchone()
   if not r:c.rollback();return None
   q=c.execute("UPDATE referrals SET total_bonus_btc=total_bonus_btc+?,bonus_paid=0 WHERE referrer_id=? AND referred_id=?",(amount,r[0],int(user_id)))
   if q.rowcount!=1:raise RuntimeError('referral_credit_lost')
   c.commit();return int(r[0])
 def eligible_completed_count(self,user_id,min_rub):
  with self._c() as c:r=c.execute("SELECT COUNT(*) FROM orders WHERE user_id=? AND status='completed' AND rub_amount>=?",(int(user_id),float(min_rub))).fetchone();return int(r[0] or 0)
 def broadcast_user_ids(self):
  rows=[];after=0
  with self._c() as c:
   while True:
    page=c.execute("SELECT user_id FROM bot_users WHERE broadcast_enabled=1 AND user_id>? ORDER BY user_id LIMIT 500",(after,)).fetchall()
    if not page:break
    rows.extend(int(r[0]) for r in page);after=int(page[-1][0])
  return rows
 def broadcast_count(self):
  with self._c() as c:return int(c.execute("SELECT COUNT(*) FROM bot_users WHERE broadcast_enabled=1").fetchone()[0])
 def disable_broadcast(self,user_id):
  with self._c() as c:q=c.execute("UPDATE bot_users SET broadcast_enabled=0 WHERE user_id=? AND broadcast_enabled=1",(int(user_id),));c.commit();return q.rowcount==1
 def order_customer_ids(self):
  rows=[];after=0
  with self._c() as c:
   while True:
    page=c.execute("SELECT DISTINCT user_id FROM orders WHERE user_id>? ORDER BY user_id LIMIT 500",(after,)).fetchall()
    if not page:break
    rows.extend(int(r[0]) for r in page);after=int(page[-1][0])
  return rows


class PostgresEngagementStore(SQLiteEngagementStore):
 def __init__(self,dsn):self.dsn=dsn
 def _c(self):
  import psycopg
  return psycopg.connect(self.dsn)
 def log_action(self,uid,action,target_id=None,details=None):
  uid,action,target_id,details=_audit_fields(uid,action,target_id,details)
  with self._c() as c:c.execute("INSERT INTO admin_log(admin_id,action,target_id,details) VALUES(%s,%s,%s,%s)",(uid,action,target_id,details))
 def vip_total(self,user_id):
  with self._c() as c:r=c.execute("SELECT total_rub FROM user_vip_volume WHERE user_id=%s",(user_id,)).fetchone();return float(r[0] or 0) if r else 0
 def add_vip(self,user_id,amount):
  with self._c() as c:c.execute("INSERT INTO user_vip_volume(user_id,total_rub,updated_at) VALUES(%s,%s,now()) ON CONFLICT(user_id) DO UPDATE SET total_rub=user_vip_volume.total_rub+excluded.total_rub,updated_at=now()",(user_id,amount))
 def toggle_rate(self,user_id):
  with self._c() as c:
   c.execute("INSERT INTO rate_subscriptions(user_id) VALUES(%s) ON CONFLICT(user_id) DO NOTHING",(user_id,));r=c.execute("UPDATE rate_subscriptions SET enabled=NOT enabled WHERE user_id=%s RETURNING enabled",(user_id,)).fetchone();return bool(r[0])
 def rate_enabled(self,user_id):
  with self._c() as c:r=c.execute("SELECT enabled FROM rate_subscriptions WHERE user_id=%s",(user_id,)).fetchone();return bool(r and r[0])
 def subscribers(self):
  rows=[];after=0
  with self._c() as c:
   while True:
    page=c.execute("SELECT user_id,last_notified,last_btc,last_ltc,last_usdt FROM rate_subscriptions WHERE enabled=true AND user_id>%s ORDER BY user_id LIMIT 500",(after,)).fetchall()
    if not page:break
    rows.extend(page);after=int(page[-1][0])
  return rows
 def update_rates(self,user_id,notified,btc,ltc,usdt):
  with self._c() as c:c.execute("UPDATE rate_subscriptions SET last_notified=%s,last_btc=%s,last_ltc=%s,last_usdt=%s WHERE user_id=%s",(notified,btc,ltc,usdt,user_id))
 def disable_rates(self,user_id):
  with self._c() as c:c.execute("UPDATE rate_subscriptions SET enabled=false WHERE user_id=%s",(user_id,))
 def review_summary(self):
  with self._c() as c:r=c.execute("SELECT COUNT(*),AVG(rating) FROM reviews WHERE status='published'").fetchone();return int(r[0]),float(r[1] or 0)
 def ensure_review(self,order_id,user_id):
  with self._c() as c:c.execute("INSERT INTO reviews(order_id,user_id,status) VALUES(%s,%s,'pending_rating') ON CONFLICT(order_id) DO NOTHING",(order_id,user_id))
 def rate_review(self,order_id,user_id,rating):
  with self._c() as c:q=c.execute("UPDATE reviews SET rating=%s,status='pending_comment' WHERE order_id=%s AND user_id=%s AND status='pending_rating' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=%s)",(rating,order_id,user_id,user_id));return q.rowcount==1
 def comment_review(self,order_id,user_id,comment):
  with self._c() as c:
   if os.getenv('BOT_B3_ENGAGEMENT_ACL_ADAPTER_ENABLED','').lower() in {'1','true','yes'}:return bool(c.execute("SELECT public.bot_b3_comment_review(%s::bigint,%s::bigint,%s::text)",(order_id,user_id,comment)).fetchone()[0])
   q=c.execute("UPDATE reviews SET comment=%s WHERE order_id=%s AND user_id=%s AND status='pending_comment' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=%s)",(comment,order_id,user_id,user_id));return q.rowcount==1
 def finalize_review(self,order_id,user_id):
  with self._c() as c:
   if os.getenv('BOT_B3_ENGAGEMENT_ACL_ADAPTER_ENABLED','').lower() in {'1','true','yes'}:
    result=c.execute("SELECT public.bot_b3_finalize_review(%s::bigint,%s::bigint)",(order_id,user_id)).fetchone()[0]
    if result is not None and not isinstance(result,dict):raise RuntimeError('invalid_review_finalize_result')
    return result
   r=c.execute("SELECT user_id,rating,comment FROM reviews WHERE order_id=%s AND user_id=%s AND status='pending_comment' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=%s) FOR UPDATE",(order_id,user_id,user_id)).fetchone()
   if not r:return None
   status='published' if r[1] and r[1]>=4 else 'admin_review';q=c.execute("UPDATE reviews SET status=%s WHERE order_id=%s AND user_id=%s AND status='pending_comment' AND EXISTS(SELECT 1 FROM orders WHERE orders.order_id=reviews.order_id AND orders.user_id=%s)",(status,order_id,user_id,user_id));return {'user_id':r[0],'rating':r[1],'comment':r[2],'status':status} if q.rowcount==1 else None
 def referral_bonus(self,user_id,date_from=None,date_to=None):
  if (date_from is None) != (date_to is None):raise ValueError('referral_bonus_date_range_required')
  if date_from is None and user_id is None:raise ValueError('referral_bonus_user_required')
  if date_from is not None and user_id is not None:raise ValueError('referral_bonus_period_is_operator_aggregate')
  with self._c() as c:
   if date_from is None:r=c.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_bonuses WHERE referrer_id=%s",(user_id,)).fetchone()
   else:r=c.execute("SELECT COALESCE(SUM(bonus_amount),0) FROM referral_bonuses WHERE created_at::date BETWEEN %s AND %s",(date_from,date_to)).fetchone()
   return float(r[0] or 0)
 def referral_stats(self,user_id):
  with self._c() as c:
   r=c.execute("SELECT COUNT(referred_id),COALESCE(SUM(total_bonus_btc),0) FROM referrals WHERE referrer_id=%s",(int(user_id),)).fetchone()
   active=c.execute("SELECT COUNT(DISTINCT r.referred_id) FROM referrals r JOIN orders o ON o.user_id=r.referred_id AND o.status='sent' WHERE r.referrer_id=%s",(int(user_id),)).fetchone()[0]
   return {'referrals':int(r[0] or 0),'active':int(active or 0),'total_bonus_btc':float(r[1] or 0)}
 def credit_referral_bonus(self,user_id,bonus_btc):
  amount=float(bonus_btc)
  if amount<=0:return None
  with self._c() as c,c.cursor() as q:
   q.execute("SELECT referrer_id FROM referrals WHERE referred_id=%s ORDER BY referrer_id FOR UPDATE LIMIT 1",(int(user_id),));r=q.fetchone()
   if not r:return None
   q.execute("UPDATE referrals SET total_bonus_btc=total_bonus_btc+%s,bonus_paid=false WHERE referrer_id=%s AND referred_id=%s",(amount,r[0],int(user_id)))
   if q.rowcount!=1:raise RuntimeError('referral_credit_lost')
   return int(r[0])
 def eligible_completed_count(self,user_id,min_rub):
  with self._c() as c:r=c.execute("SELECT COUNT(*) FROM orders WHERE user_id=%s AND status='completed' AND rub_amount>=%s",(int(user_id),float(min_rub))).fetchone();return int(r[0] or 0)
 def broadcast_user_ids(self):
  rows=[];after=0
  with self._c() as c:
   while True:
    page=c.execute("SELECT user_id FROM bot_users WHERE broadcast_enabled=true AND user_id>%s ORDER BY user_id LIMIT 500",(after,)).fetchall()
    if not page:break
    rows.extend(int(r[0]) for r in page);after=int(page[-1][0])
  return rows
 def broadcast_count(self):
  with self._c() as c:return int(c.execute("SELECT COUNT(*) FROM bot_users WHERE broadcast_enabled=true").fetchone()[0])
 def disable_broadcast(self,user_id):
  with self._c() as c:q=c.execute("UPDATE bot_users SET broadcast_enabled=false WHERE user_id=%s AND broadcast_enabled=true",(int(user_id),));return q.rowcount==1
 def order_customer_ids(self):
  rows=[];after=0
  with self._c() as c:
   while True:
    page=c.execute("SELECT DISTINCT user_id FROM orders WHERE user_id>%s ORDER BY user_id LIMIT 500",(after,)).fetchall()
    if not page:break
    rows.extend(int(r[0]) for r in page);after=int(page[-1][0])
  return rows


def from_environment(*,sqlite_path):
 url=os.getenv('DATABASE_URL','').strip()
 if not url:return SQLiteEngagementStore(sqlite_path)
 if db_runtime.backend(url)!='postgresql' or os.getenv('ENGAGEMENT_POSTGRES_ENABLED','').lower() not in {'1','true','yes'}:raise RuntimeError('postgres_engagement_store_not_enabled')
 return PostgresEngagementStore(url)
