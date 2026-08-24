import os
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 bot B5.3 adapter PostgreSQL: skipped")
    raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.bot_notification_store import PostgresB5BotNotificationStore


with psycopg.connect(dsn) as connection:
    connection.execute(
        "CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,"
        "blocked_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,"
        "created_at timestamptz NOT NULL,currency text NOT NULL,rub_amount numeric NOT NULL,"
        "status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,"
        "receipt_deadline timestamptz,montera_invoice_id text,updated_at timestamptz,network text);"
        "CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,"
        "PRIMARY KEY(order_id,event));"
        "CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,"
        "updated_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,order_id bigint NOT NULL,"
        "status text NOT NULL,session_token text NOT NULL);"
        "CREATE TABLE order_receipts(order_id bigint NOT NULL);"
        "CREATE TABLE promo_codes(id bigserial PRIMARY KEY,code text UNIQUE NOT NULL,"
        "discount_percent numeric NOT NULL,max_uses integer NOT NULL,"
        "uses_count integer NOT NULL DEFAULT 0,valid_until timestamptz NOT NULL,"
        "is_active boolean NOT NULL DEFAULT true);"
        "CREATE TABLE bot_notification_jobs(id bigserial PRIMARY KEY,kind text NOT NULL,"
        "dedupe_key text NOT NULL,payload jsonb NOT NULL,state text NOT NULL DEFAULT 'pending',"
        "attempts integer NOT NULL DEFAULT 0,created_at timestamptz NOT NULL DEFAULT now(),"
        "claimed_at timestamptz,sent_at timestamptz,updated_at timestamptz NOT NULL DEFAULT now(),"
        "UNIQUE(kind,dedupe_key))"
    )
    now = connection.execute("SELECT now()").fetchone()[0]
    connection.execute(
        "INSERT INTO orders VALUES"
        "(1,101,%s-'10 minutes'::interval,'BTC',1000,'pending',NULL,NULL,NULL,NULL,NULL,%s-'10 minutes'::interval,NULL),"
        "(2,102,%s,'BTC',1000,'pending',NULL,NULL,NULL,%s+'10 minutes'::interval,'INV',%s,NULL),"
        "(3,103,%s-'1 hour'::interval,'LTC',1000,'paid',NULL,'',NULL,NULL,NULL,%s-'30 minutes'::interval,NULL),"
        "(4,104,%s-'20 days'::interval,'BTC',1000,'sent',NULL,'tx',NULL,NULL,NULL,%s-'20 days'::interval,NULL),"
        "(5,105,%s-'3 hours'::interval,'BTC',1000,'expired',NULL,NULL,NULL,NULL,NULL,%s-'2 hours'::interval,NULL)",
        (now, now, now, now, now, now, now, now, now, now, now),
    )
    connection.execute(
        "INSERT INTO payment_sessions(order_id,status,session_token) VALUES(1,'created','tok')"
    )
    connection.execute(
        (ROOT / "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql").read_text()
    )
    connection.execute(
        (ROOT / "deploy/postgres/proposals/048_e0_bot_b5_3_notification_queue_writers.sql").read_text()
    )

parts = conninfo_to_dict(dsn)
parts.update(user="obsidian_exchange_bot", password="synthetic-rehearsal-only")
bot_dsn = make_conninfo(**parts)


def store():
    return PostgresB5BotNotificationStore(bot_dsn)


assert store().queue_due_abandoned(now=now, limit=200) == 1
assert store().queue_due_montera(now=now, limit=200) == 1
assert store().queue_due_payout_delays(warn_minutes=15, now=now, limit=200) == 1
assert store().queue_due_recalls(now=now, limit=200) == 1
assert store().queue_due_winbacks(discount=5, valid_hours=72, now=now, limit=200) == 1
assert store().queue_due_abandoned(now=now, limit=200) == 0

with ThreadPoolExecutor(max_workers=8) as pool:
    claimed = list(pool.map(lambda _item: store().claim_notification(), range(8)))
items = [item for item in claimed if item is not None]
assert len(items) == 6
assert len({item["id"] for item in items}) == 6
assert all(item["attempts"] == 1 for item in items)
assert store().mark_notification_sent(items[0]["id"]) is True
assert store().mark_notification_sent(items[0]["id"]) is False
assert store().retry_notification(items[1]["id"]) is True

for invalid in (
    lambda: store().queue_due_payout_delays(warn_minutes=-1, now=now, limit=1),
    lambda: store().queue_due_winbacks(discount=101, valid_hours=1, now=now, limit=1),
):
    try:
        invalid()
    except psycopg.Error:
        pass
    else:
        raise AssertionError("invalid parameters unexpectedly fell back or succeeded")

with psycopg.connect(dsn) as connection:
    assert connection.execute("SELECT count(*) FROM bot_notification_jobs").fetchone() == (6,)
    assert connection.execute(
        "SELECT has_table_privilege('obsidian_exchange_bot','bot_notification_jobs','SELECT'),"
        "has_table_privilege('obsidian_exchange_bot','sent_notifications','INSERT'),"
        "has_sequence_privilege('obsidian_exchange_bot','bot_notification_jobs_id_seq','USAGE')"
    ).fetchone() == (False, False, False)
    assert connection.execute(
        "SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid=p.pronamespace "
        "WHERE n.nspname='public' AND p.proname LIKE 'bot_b5_notification_%' "
        "AND has_function_privilege('obsidian_exchange_bot',p.oid,'EXECUTE')"
    ).fetchone() == (3,)

print("E0.3 bot B5.3 full execute-only adapter PostgreSQL path: OK")
