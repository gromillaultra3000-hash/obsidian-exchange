import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres gift store: skipped');raise SystemExit(0)
from repositories.gift_store import PostgresGiftStore,GiftCodeConflict
s=PostgresGiftStore(dsn);assert not s.code_exists('GIFT') and s.card(999999999) is None;g=s.issue(sender_id=1,currency='BTC',rub_amount=100,code='GIFT',destination='placeholder',agreed_rate=10,agreed_crypto_amount=10);assert s.code_exists('GIFT');card=s.card(g['gift_id']);assert card[0]=='BTC' and float(card[1])==100 and card[2]=='GIFT'
try:s.issue(sender_id=1,currency='BTC',rub_amount=100,code='GIFT',destination='x',agreed_rate=10,agreed_crypto_amount=10);raise AssertionError()
except GiftCodeConflict:pass
with s._connect() as c,c.cursor() as q:q.execute("UPDATE gift_vouchers SET status='paid' WHERE id=%s",(g['gift_id'],))
assert s.redeem(gift_id=g['gift_id'],recipient_id=1,destination='self',agreed_rate=11,agreed_crypto_amount=9)['action']=='own_gift'
assert s.redeem(gift_id=g['gift_id'],recipient_id=2,destination='dest',agreed_rate=11,agreed_crypto_amount=9)['action']=='redeemed'
assert s.redeem(gift_id=g['gift_id'],recipient_id=3,destination='dest2',agreed_rate=11,agreed_crypto_amount=9)['action']=='not_redeemable'
print('PostgreSQL gift repository checks: OK')
