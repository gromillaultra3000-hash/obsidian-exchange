import os,sys,threading
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.engagement_store import PostgresEngagementStore
s=PostgresEngagementStore(os.environ['TEST_POSTGRES_DSN'])
with s._c() as c:
 c.execute("DELETE FROM reviews WHERE order_id=1");c.execute("DELETE FROM orders WHERE order_id=1")
 c.execute("DELETE FROM user_vip_volume WHERE user_id=7");c.execute("DELETE FROM rate_subscriptions WHERE user_id=7")
 c.execute("INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status) VALUES(1,7,'BTC',1,'a','sent')")
 c.execute("INSERT INTO bot_users(user_id,broadcast_enabled) VALUES(7,true) ON CONFLICT(user_id) DO UPDATE SET broadcast_enabled=true")
s.log_action(9,'x',1,'d')
for args in ((0,'x',1,'d'),(9,'',1,'d'),(9,'x'*81,1,'d'),(9,'x',1,'d'*501)):
 try:s.log_action(*args);assert False
 except ValueError:pass
s.add_vip(7,100);s.add_vip(7,50);assert s.vip_total(7)==150
assert s.toggle_rate(7) is False and s.toggle_rate(7) is True;s.update_rates(7,1,2,3,4);assert len(s.subscribers())==1;s.disable_rates(7);assert not s.rate_enabled(7)
s.ensure_review(1,7);assert s.rate_review(1,7,5) and not s.rate_review(1,7,4)
assert not s.comment_review(1,8,'foreign') and s.finalize_review(1,8) is None
assert s.comment_review(1,7,'ok') and s.finalize_review(1,7)['status']=='published';assert s.review_summary()==(1,5.0)
with s._c() as c:
 c.execute("DELETE FROM referrals WHERE referred_id=991207");c.execute("DELETE FROM orders WHERE order_id=991207")
 c.execute("INSERT INTO referrals(referrer_id,referred_id,total_bonus_btc) VALUES(991209,991207,.001)")
 c.execute("INSERT INTO orders(order_id,user_id,currency,rub_amount,crypto_address,status) VALUES(991207,991207,'BTC',1,'a','sent')")
assert s.referral_stats(991209)=={'referrals':1,'active':1,'total_bonus_btc':.001}
assert s.credit_referral_bonus(991207,.002)==991209
assert s.referral_stats(991209)['total_bonus_btc']==.003
assert s.credit_referral_bonus(999999999,.1) is None
assert s.broadcast_user_ids() and 7 in s.broadcast_user_ids()
assert s.broadcast_count()>=1 and 7 in s.order_customer_ids()
with s._c() as c:c.execute("UPDATE bot_users SET broadcast_enabled=true WHERE user_id=7")
wins=[];threads=[threading.Thread(target=lambda:wins.append(s.disable_broadcast(7))) for _ in range(8)]
[t.start() for t in threads];[t.join() for t in threads]
assert sum(wins)==1 and not s.disable_broadcast(7)
with s._c() as c:c.execute("DELETE FROM referrals WHERE referred_id=991207");c.execute("DELETE FROM orders WHERE order_id=991207")
print('PostgreSQL engagement repository checks: OK')
