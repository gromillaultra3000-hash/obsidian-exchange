import os,sys
from datetime import datetime,timedelta,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/"relay"))
dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn: print("postgres bot order store: skipped");raise SystemExit(0)
from repositories.bot_order_store import PostgresBotOrderStore
store=PostgresBotOrderStore(dsn); future=datetime.now(timezone.utc)+timedelta(minutes=15)
lid=store.replace_rate_lock(user_id=7,currency="BTC",locked_rate=10_000_000,fee_rub=100,locked_until=future)
r=store.create_order(user_id=7,username="u",currency="BTC",rub_amount=10000,destination="dest",
 network=None,preferred_rate=12_000_000,preferred_crypto_amount=.00083333,
 fallback_rate=13_000_000,fallback_crypto_amount=.00076923,lock_id=lid)
assert r["lock_used"]
r2=store.create_order(user_id=7,username="u",currency="BTC",rub_amount=10000,destination="dest2",
 network=None,preferred_rate=12_000_000,preferred_crypto_amount=.00083333,
 fallback_rate=13_000_000,fallback_crypto_amount=.00076923,lock_id=lid)
assert not r2["lock_used"] and r2["agreed_rate"]==13_000_000
p=store.create_order(user_id=10,username="p",currency="BTC",rub_amount=1,destination="p",
 network=None,preferred_rate=9,preferred_crypto_amount=2,fallback_rate=9,
 fallback_crypto_amount=2,promo_id=1,lock_no_promo_rate=10,
 lock_no_promo_crypto_amount=1,regular_no_promo_rate=10,regular_no_promo_crypto_amount=1)
assert p["promo_used"] and p["agreed_rate"]==9
p2=store.create_order(user_id=11,username="p2",currency="BTC",rub_amount=1,destination="p2",
 network=None,preferred_rate=9,preferred_crypto_amount=2,fallback_rate=9,
 fallback_crypto_amount=2,promo_id=1,lock_no_promo_rate=10,
 lock_no_promo_crypto_amount=1,regular_no_promo_rate=10,regular_no_promo_crypto_amount=1)
assert not p2["promo_used"] and p2["agreed_rate"]==10
print("PostgreSQL bot order/rate-lock repository checks: OK")
