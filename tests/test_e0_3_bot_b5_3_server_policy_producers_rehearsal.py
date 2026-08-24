import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 bot B5.3 server-policy producers: skipped")
    raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as connection:
    connection.execute(
        "CREATE ROLE obsidian_exchange_bot_delivery_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_delivery LOGIN PASSWORD 'synthetic-delivery-only' NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_transport_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_transport LOGIN PASSWORD 'synthetic-transport-only' NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_background_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_background LOGIN PASSWORD 'synthetic-background-only' NOINHERIT;"
        "CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL,currency text NOT NULL,rub_amount numeric NOT NULL,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,receipt_deadline timestamptz,montera_invoice_id text,updated_at timestamptz,network text);"
        "CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event));"
        "CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,order_id bigint NOT NULL,status text NOT NULL,session_token text NOT NULL);"
        "CREATE TABLE order_receipts(order_id bigint NOT NULL);"
        "CREATE TABLE promo_codes(id bigserial PRIMARY KEY,code text UNIQUE NOT NULL,discount_percent numeric NOT NULL,max_uses integer NOT NULL,uses_count integer NOT NULL DEFAULT 0,valid_until timestamptz NOT NULL,is_active boolean NOT NULL DEFAULT true)"
    )
    connection.execute((ROOT / "deploy/postgres/023_bot_notification_jobs.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/proposals/048_e0_bot_b5_3_notification_queue_writers.sql").read_text())
    connection.execute("GRANT CONNECT ON DATABASE " + connection.info.dbname + " TO obsidian_exchange_bot_delivery,obsidian_exchange_bot_transport,obsidian_exchange_bot_background")
    connection.execute((ROOT / "deploy/postgres/proposals/058_e0_bot_b5_3_hardened_delivery_lifecycle.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/proposals/059_e0_bot_b5_3_server_policy_producers.sql").read_text())
    now = connection.execute("SELECT clock_timestamp()").fetchone()[0]
    policy_id = connection.execute(
        "INSERT INTO bot_notification_policy_versions(version,policy_sha256,approval_evidence_sha256,effective_from,effective_until,recall_enabled,montera_enabled,abandoned_enabled,payout_delay_enabled,payout_warn_minutes,winback_enabled,winback_discount,winback_valid_hours,max_attempts,admin_recipient_ids,approved_by,approved_at) "
        "VALUES(7,%s,%s,%s-interval '1 second',%s+interval '1 day',true,true,true,true,15,true,5,72,4,ARRAY[9001::bigint,9002::bigint],1,%s-interval '2 seconds') RETURNING policy_id",
        (None, "b" * 64, now, now, now),
    ).fetchone()[0]
    connection.execute("INSERT INTO bot_notification_policy_current(policy_id,policy_version,activated_by) VALUES(%s,7,1)", (policy_id,))
    connection.execute(
        "INSERT INTO orders VALUES"
        "(1,101,%s-'10 minutes'::interval,'BTC',1000,'pending',NULL,NULL,NULL,NULL,NULL,%s-'10 minutes'::interval,NULL),"
        "(2,102,%s,'BTC',1000,'pending',NULL,NULL,NULL,%s+'10 minutes'::interval,'INV',%s,NULL),"
        "(3,103,%s-'1 hour'::interval,'LTC',1000,'paid',NULL,'',NULL,NULL,NULL,%s-'30 minutes'::interval,NULL),"
        "(4,104,%s-'20 days'::interval,'BTC',1000,'sent',NULL,'tx',NULL,NULL,NULL,%s-'20 days'::interval,NULL),"
        "(5,105,%s-'3 hours'::interval,'BTC',1000,'expired',NULL,NULL,NULL,NULL,NULL,%s-'2 hours'::interval,NULL)",
        (now, now, now, now, now, now, now, now, now, now, now),
    )
    connection.execute("INSERT INTO payment_sessions(order_id,status,session_token) VALUES(1,'created','tok')")

parts = conninfo_to_dict(dsn)
parts.update(user="obsidian_exchange_bot_background", password="synthetic-background-only")
background_dsn = make_conninfo(**parts)


def call(name):
    with psycopg.connect(background_dsn) as connection:
        return connection.execute(f"SELECT public.{name}(200)").fetchone()[0]


with psycopg.connect(dsn) as connection:
    connection.execute(
        "CREATE FUNCTION fail_second_admin() RETURNS trigger LANGUAGE plpgsql AS $$"
        "BEGIN IF NEW.kind='montera_admin' AND NEW.recipient_id=9002 THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END$$;"
        "CREATE TRIGGER fail_second_admin BEFORE INSERT ON bot_notification_jobs FOR EACH ROW EXECUTE FUNCTION fail_second_admin()"
    )
try:
    call("bot_b59_queue_due_montera")
except psycopg.Error:
    pass
else:
    raise AssertionError("admin fanout fault did not abort")
with psycopg.connect(dsn) as connection:
    assert connection.execute("SELECT count(*) FROM bot_notification_jobs").fetchone() == (0,)
    assert connection.execute("SELECT count(*) FROM sent_notifications").fetchone() == (0,)
    connection.execute("DROP TRIGGER fail_second_admin ON bot_notification_jobs;DROP FUNCTION fail_second_admin()")

for name in (
    "bot_b59_queue_due_abandoned",
    "bot_b59_queue_due_montera",
    "bot_b59_queue_due_payout_delays",
    "bot_b59_queue_due_recalls",
    "bot_b59_queue_due_winbacks",
):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _n: call(name), range(8)))
    assert sum(results) == 1, (name, results)

with psycopg.connect(dsn) as connection:
    jobs = connection.execute(
        "SELECT kind,recipient_id,policy_version,max_attempts,payload->>'user_id' subject_id FROM bot_notification_jobs ORDER BY id"
    ).fetchall()
    assert len(jobs) == 7
    assert [row[1] for row in jobs if row[0] == "montera_admin"] == [9001, 9002]
    assert all(row[2] == 7 and row[3] == 4 for row in jobs)
    assert all(row[4] == "102" for row in jobs if row[0] == "montera_admin")
    assert connection.execute("SELECT count(*) FROM sent_notifications").fetchone() == (5,)
    assert connection.execute("SELECT discount_percent,max_uses FROM promo_codes").fetchone() == (5, 1)
    assert connection.execute("SELECT policy_sha256 ~ '^[0-9a-f]{64}$' FROM bot_notification_policy_versions WHERE version=7").fetchone() == (True,)
    try:
        connection.execute("UPDATE bot_notification_policy_versions SET winback_discount=10 WHERE version=7")
    except psycopg.Error as exc:
        assert "notification_policy_immutable" in str(exc)
        connection.rollback()
    else:
        raise AssertionError("approved policy mutated")
    assert connection.execute(
        "SELECT has_table_privilege('obsidian_exchange_bot_background','bot_notification_jobs','INSERT'),"
        "has_sequence_privilege('obsidian_exchange_bot_background','bot_notification_jobs_id_seq','USAGE'),"
        "has_function_privilege('obsidian_exchange_bot_background',to_regprocedure('bot_b59_queue_due_montera(integer)'),'EXECUTE'),"
        "has_function_privilege('obsidian_exchange_bot',to_regprocedure('bot_b5_queue_due_montera(timestamp with time zone,integer)'),'EXECUTE')"
    ).fetchone() == (False, False, True, False)

print("E0.3 B5.3 server-time policy-bound per-recipient producers, concurrency and rollback: OK")
