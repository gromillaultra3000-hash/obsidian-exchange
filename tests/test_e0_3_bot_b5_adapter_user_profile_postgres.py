import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 bot B5 user-profile adapter PostgreSQL: skipped")
    raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.user_profile_store import PostgresUserProfileStore


with psycopg.connect(dsn) as connection:
    connection.execute(
        "CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,"
        "blocked_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,"
        "created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',"
        "rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL DEFAULT 'pending',"
        "crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,"
        "updated_at timestamptz,network text);"
        "CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,"
        "updated_at timestamptz NOT NULL DEFAULT now())"
    )
    connection.execute((ROOT / "deploy/postgres/008_support.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/011_user_profiles.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/013_promos.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/018_provider_health.sql").read_text())
    connection.execute(
        (ROOT / "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql").read_text()
    )
    connection.execute(
        (ROOT / "deploy/postgres/proposals/047_e0_bot_b5_2_residual_identity_support_config_writers.sql").read_text()
    )

parts = conninfo_to_dict(dsn)
parts.update(user="obsidian_exchange_bot", password="synthetic-rehearsal-only")
bot_dsn = make_conninfo(**parts)


def make_store():
    return PostgresUserProfileStore(bot_dsn, use_b5_acl_functions=True)


make_store().upsert_user(user_id=20, username="first", first_name="A", last_name="B")
make_store().upsert_user(user_id=20, username="second", first_name=None, last_name=None)

with ThreadPoolExecutor(max_workers=8) as pool:
    claims = list(
        pool.map(
            lambda referrer_id: make_store().claim_referrer(
                referred_id=30, referrer_id=referrer_id
            ),
            range(100, 108),
        )
    )
assert sum(claims) == 1
assert make_store().claim_referrer(referred_id=30, referrer_id=999) is False
assert make_store().claim_referrer(referred_id=30, referrer_id=30) is False

with psycopg.connect(dsn) as connection:
    assert connection.execute(
        "SELECT username,first_name,last_name FROM bot_users WHERE user_id=20"
    ).fetchone() == ("second", None, None)
    assert connection.execute(
        "SELECT count(*) FROM referrals WHERE referred_id=30"
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT has_table_privilege('obsidian_exchange_bot','bot_users','INSERT'),"
        "has_table_privilege('obsidian_exchange_bot','referrals','INSERT'),"
        "has_function_privilege('obsidian_exchange_bot',"
        "to_regprocedure('bot_b5_upsert_user(bigint,text,text,text)'),'EXECUTE'),"
        "has_function_privilege('obsidian_exchange_bot',"
        "to_regprocedure('bot_b5_claim_referrer(bigint,bigint)'),'EXECUTE')"
    ).fetchone() == (False, False, True, True)

print("E0.3 bot B5 user-profile adapter execute-only PostgreSQL path: OK")
