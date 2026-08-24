import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 bot B5.3 hardened delivery lifecycle: skipped")
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
        "CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,"
        "blocked_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,"
        "created_at timestamptz NOT NULL,currency text NOT NULL,rub_amount numeric NOT NULL,"
        "status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,"
        "receipt_deadline timestamptz,montera_invoice_id text,updated_at timestamptz,network text);"
        "CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event));"
        "CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,order_id bigint NOT NULL,status text NOT NULL,session_token text NOT NULL);"
        "CREATE TABLE order_receipts(order_id bigint NOT NULL);"
        "CREATE TABLE promo_codes(id bigserial PRIMARY KEY,code text UNIQUE NOT NULL,discount_percent numeric NOT NULL,"
        "max_uses integer NOT NULL,uses_count integer NOT NULL DEFAULT 0,valid_until timestamptz NOT NULL,is_active boolean NOT NULL DEFAULT true)"
    )
    connection.execute((ROOT / "deploy/postgres/023_bot_notification_jobs.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql").read_text())
    connection.execute((ROOT / "deploy/postgres/proposals/048_e0_bot_b5_3_notification_queue_writers.sql").read_text())
    connection.execute(
        "GRANT CONNECT ON DATABASE " + connection.info.dbname +
        " TO obsidian_exchange_bot_delivery,obsidian_exchange_bot_transport"
    )
    connection.execute((ROOT / "deploy/postgres/proposals/058_e0_bot_b5_3_hardened_delivery_lifecycle.sql").read_text())
    connection.execute(
        "INSERT INTO bot_notification_jobs(kind,dedupe_key,payload,recipient_id,max_attempts) VALUES"
        "('recall','1','{\"user_id\":101}',101,3),"
        "('payout_delayed','2','{\"user_id\":102}',102,3),"
        "('pay_reminder','3','{\"user_id\":103}',103,1),"
        "('recall','4','{\"user_id\":104}',104,3)"
    )

parts = conninfo_to_dict(dsn)
delivery_parts = dict(parts, user="obsidian_exchange_bot_delivery", password="synthetic-delivery-only")
transport_parts = dict(parts, user="obsidian_exchange_bot_transport", password="synthetic-transport-only")
delivery_dsn = make_conninfo(**delivery_parts)
transport_dsn = make_conninfo(**transport_parts)


def delivery(sql, args=()):
    with psycopg.connect(delivery_dsn) as connection:
        return connection.execute(sql, args).fetchone()


def transport(job_id, token, outcome, reason=None, request=None, message=None):
    with psycopg.connect(transport_dsn) as connection:
        return connection.execute(
            "SELECT bot_b53_transport_record_evidence(%s,%s,%s,%s,%s,%s,%s,clock_timestamp())",
            (job_id, token, outcome, request, message, reason, "a" * 64),
        ).fetchone()[0]


with ThreadPoolExecutor(max_workers=8) as pool:
    claimed = list(pool.map(lambda _n: delivery("SELECT * FROM bot_b53_delivery_claim(NULL)"), range(8)))
items = [row for row in claimed if row]
assert len(items) == 4
assert len({row[0] for row in items}) == 4
assert len({row[6] for row in items}) == 4

by_id = {row[0]: row for row in items}
first, second, third, fourth = by_id[1], by_id[2], by_id[3], by_id[4]

accepted = transport(first[0], first[6], "ACCEPTED", request="req-1", message="msg-1")
try:
    transport(first[0], first[6], "NOT_STARTED", reason="PROVIDER_REJECTED_PRE_SUBMIT")
except psycopg.Error as exc:
    assert "conflicting_delivery_evidence" in str(exc)
else:
    raise AssertionError("conflicting terminal evidence was accepted")
assert delivery("SELECT bot_b53_delivery_mark_sent(%s,%s,%s)", (first[0], first[6], accepted)) == (True,)
assert delivery("SELECT bot_b53_delivery_mark_sent(%s,%s,%s)", (first[0], first[6], accepted)) == (False,)

not_started = transport(second[0], second[6], "NOT_STARTED", reason="PROVIDER_REJECTED_PRE_SUBMIT")
assert delivery("SELECT bot_b53_delivery_retry_pre_submit(%s,%s,%s)", (second[0], second[6], not_started)) == ("RETRY",)
reclaimed = delivery("SELECT * FROM bot_b53_delivery_claim('payout_delayed')")
assert reclaimed[0] == second[0] and reclaimed[6] != second[6] and reclaimed[4] == 2
assert delivery("SELECT bot_b53_delivery_mark_sent(%s,%s,%s)", (second[0], second[6], accepted)) == (False,)
uncertain = transport(reclaimed[0], reclaimed[6], "UNCERTAIN", reason="TRANSPORT_UNCERTAIN")
assert delivery("SELECT bot_b53_delivery_mark_manual(%s,%s,%s)", (reclaimed[0], reclaimed[6], uncertain)) == (True,)
assert delivery("SELECT * FROM bot_b53_delivery_claim('payout_delayed')") is None

maxed = transport(third[0], third[6], "NOT_STARTED", reason="PROVIDER_REJECTED_PRE_SUBMIT")
assert delivery("SELECT bot_b53_delivery_retry_pre_submit(%s,%s,%s)", (third[0], third[6], maxed)) == ("MANUAL",)

fault_evidence = transport(fourth[0], fourth[6], "ACCEPTED", request="req-4", message="msg-4")
with psycopg.connect(dsn) as connection:
    connection.execute(
        "CREATE FUNCTION fail_b53_sent() RETURNS trigger LANGUAGE plpgsql AS $$"
        "BEGIN IF NEW.id=4 AND NEW.state='sent' THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END$$;"
        "CREATE TRIGGER fail_b53_sent BEFORE UPDATE ON bot_notification_jobs "
        "FOR EACH ROW EXECUTE FUNCTION fail_b53_sent()"
    )
try:
    delivery("SELECT bot_b53_delivery_mark_sent(%s,%s,%s)", (fourth[0], fourth[6], fault_evidence))
except psycopg.Error:
    pass
else:
    raise AssertionError("injected transition fault did not roll back")

with psycopg.connect(dsn) as connection:
    assert connection.execute(
        "SELECT state,manual_reason_code FROM bot_notification_jobs ORDER BY id"
    ).fetchall() == [("sent", None), ("manual", "TRANSPORT_UNCERTAIN"), ("manual", "MAX_ATTEMPTS"), ("sending", None)]
    assert connection.execute(
        "SELECT count(*),count(DISTINCT attempt_token) FROM bot_notification_delivery_attempts"
    ).fetchone() == (5, 5)
    assert connection.execute(
        "SELECT count(*) FROM bot_notification_delivery_evidence WHERE consumed_at IS NOT NULL"
    ).fetchone() == (4,)
    assert connection.execute(
        "SELECT consumed_at,consumed_transition FROM bot_notification_delivery_evidence WHERE evidence_id=%s",
        (fault_evidence,),
    ).fetchone() == (None, None)
    assert connection.execute(
        "SELECT has_table_privilege('obsidian_exchange_bot_delivery','bot_notification_jobs','SELECT'),"
        "has_table_privilege('obsidian_exchange_bot_transport','bot_notification_delivery_evidence','INSERT'),"
        "has_function_privilege('obsidian_exchange_bot_delivery',to_regprocedure('bot_b53_delivery_claim(text)'),'EXECUTE'),"
        "has_function_privilege('obsidian_exchange_bot_transport',to_regprocedure('bot_b53_transport_record_evidence(bigint,uuid,text,text,text,text,text,timestamp with time zone)'),'EXECUTE'),"
        "has_function_privilege('obsidian_exchange_bot',to_regprocedure('bot_b5_notification_claim(text)'),'EXECUTE')"
    ).fetchone() == (False, False, True, True, False)
    assert connection.execute(
        "SELECT count(*) FROM pg_auth_members WHERE roleid IN(SELECT oid FROM pg_roles WHERE rolname LIKE 'obsidian_exchange_bot_%') "
        "OR member IN(SELECT oid FROM pg_roles WHERE rolname LIKE 'obsidian_exchange_bot_%')"
    ).fetchone() == (0,)

print("E0.3 B5.3 token/evidence-bound delivery, replay, ABA, max-attempt and privilege denial: OK")
