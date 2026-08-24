import sqlite3,sys,tempfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT/'relay'))
from repositories.user_profile_store import SQLiteUserProfileStore
with tempfile.TemporaryDirectory() as td:
 p=str(Path(td)/'u.db')
 with sqlite3.connect(p) as c:c.executescript("""CREATE TABLE bot_users(user_id INTEGER PRIMARY KEY,username TEXT,first_name TEXT,last_name TEXT,first_seen TEXT DEFAULT CURRENT_TIMESTAMP,last_seen TEXT DEFAULT CURRENT_TIMESTAMP,broadcast_enabled INTEGER DEFAULT 1);CREATE TABLE referrals(referrer_id INTEGER,referred_id INTEGER,bonus_paid INTEGER DEFAULT 0,created_at TEXT DEFAULT CURRENT_TIMESTAMP,total_bonus_btc REAL DEFAULT 0,PRIMARY KEY(referrer_id,referred_id));CREATE TABLE referral_addresses(user_id INTEGER PRIMARY KEY,currency TEXT,address TEXT);""")
 s=SQLiteUserProfileStore(p);s.upsert_user(user_id=1,username='u',first_name='A',last_name='B');s.upsert_user(user_id=1,username='v',first_name='C',last_name='D');assert s.claim_referrer(referred_id=2,referrer_id=1);assert not s.claim_referrer(referred_id=2,referrer_id=3);assert not s.claim_referrer(referred_id=2,referrer_id=2);s.set_referral_address(user_id=2,currency='BTC',address='a');s.set_referral_address(user_id=2,currency='BTC',address='b');assert s.referral_address(user_id=2,currency='BTC')=='b';assert s.referral_address(user_id=2,currency='LTC') is None
 with sqlite3.connect(p) as c:assert c.execute('SELECT username FROM bot_users').fetchone()[0]=='v' and c.execute('SELECT referrer_id FROM referrals').fetchone()[0]==1 and c.execute('SELECT address FROM referral_addresses').fetchone()[0]=='b'
print('SQLite user-profile repository checks: OK')
