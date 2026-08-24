import os,sys
from datetime import datetime,timezone
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
dsn=os.getenv('TEST_POSTGRES_DSN')
if not dsn:print('postgres wallet store: skipped');raise SystemExit(0)
from repositories.wallet_store import PostgresWalletStore
s=PostgresWalletStore(dsn);now=datetime.now(timezone.utc);s.remember_link(user_id=1,chain='TON',address='a',verified_at=now);assert s.links_for(1);iid=s.remember_intent(user_id=1,chain='TON',sell_id=2,from_address='a',to_address='b',amount=1,marker='m',created_at=now);assert iid and s.mark_signed(user_id=1,sell_id=2,signed_at=now) and not s.mark_signed(user_id=1,sell_id=2,signed_at=now)
print('PostgreSQL wallet repository checks: OK')
