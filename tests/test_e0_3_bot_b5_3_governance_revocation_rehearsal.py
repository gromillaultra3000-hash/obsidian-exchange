import os
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path


dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 bot B5.3 governance/revocation: skipped")
    raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.bot_notification_store import PostgresB53HardenedBotNotificationStore
with psycopg.connect(dsn) as db:
    db.execute(
        "CREATE ROLE obsidian_exchange_bot_delivery_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_delivery LOGIN PASSWORD 'synthetic-delivery-only' NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_transport_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_transport LOGIN PASSWORD 'synthetic-transport-only' NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_background_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_background LOGIN PASSWORD 'synthetic-background-only' NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_governance_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_policy_approver LOGIN PASSWORD 'synthetic-approver-only' NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_reconciler_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_reconciler LOGIN PASSWORD 'synthetic-reconciler-only' NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_notification_reconciler_owner NOLOGIN NOINHERIT;"
        "CREATE ROLE obsidian_exchange_bot_notification_reconciler LOGIN PASSWORD 'synthetic-notification-reconciler-only' NOINHERIT;"
        "CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint NOT NULL,created_at timestamptz NOT NULL,currency text NOT NULL,rub_amount numeric NOT NULL,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,receipt_deadline timestamptz,montera_invoice_id text,updated_at timestamptz,network text);"
        "CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event));"
        "CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz NOT NULL DEFAULT now());"
        "CREATE TABLE payment_sessions(id bigserial PRIMARY KEY,order_id bigint NOT NULL,status text NOT NULL,session_token text NOT NULL);"
        "CREATE TABLE order_receipts(order_id bigint NOT NULL);"
        "CREATE TABLE promo_codes(id bigserial PRIMARY KEY,code text UNIQUE NOT NULL,discount_percent numeric NOT NULL,max_uses integer NOT NULL,uses_count integer NOT NULL DEFAULT 0,valid_until timestamptz NOT NULL,is_active boolean NOT NULL DEFAULT true)"
    )
    for path in (
        "deploy/postgres/023_bot_notification_jobs.sql",
        "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql",
        "deploy/postgres/proposals/048_e0_bot_b5_3_notification_queue_writers.sql",
        "deploy/postgres/proposals/058_e0_bot_b5_3_hardened_delivery_lifecycle.sql",
        "deploy/postgres/proposals/059_e0_bot_b5_3_server_policy_producers.sql",
        "deploy/postgres/proposals/060_e0_bot_b5_3_policy_governance_recipient_revocation.sql",
        "deploy/postgres/proposals/061_e0_bot_b5_3_pre_submit_authorization.sql",
        "deploy/postgres/proposals/062_e0_bot_b5_3_truthful_evidence_reconciliation.sql",
        "deploy/postgres/proposals/063_e0_bot_b5_3_stale_review_reconciler.sql",
    ):
        db.execute((ROOT / path).read_text())
    for role in ("delivery", "transport", "background", "policy_approver", "reconciler", "notification_reconciler"):
        db.execute(f"GRANT CONNECT ON DATABASE {db.info.dbname} TO obsidian_exchange_bot_{role}")
    now = db.execute("SELECT clock_timestamp()").fetchone()[0]
    policy_id, digest = db.execute(
        "INSERT INTO bot_notification_policy_versions(version,policy_sha256,approval_evidence_sha256,effective_from,effective_until,recall_enabled,montera_enabled,abandoned_enabled,payout_delay_enabled,payout_warn_minutes,winback_enabled,winback_discount,winback_valid_hours,max_attempts,admin_recipient_ids,approved_by,approved_at) "
        "VALUES(7,NULL,%s,%s-interval '1 second',%s+interval '1 day',true,true,true,true,15,true,5,72,4,ARRAY[9001::bigint,9002::bigint],1,%s-interval '2 seconds') RETURNING policy_id,policy_sha256",
        ("b" * 64, now, now, now),
    ).fetchone()

parts = conninfo_to_dict(dsn)
def role_dsn(role, password):
    values = dict(parts); values.update(user=role, password=password); return make_conninfo(**values)

adapter = PostgresB53HardenedBotNotificationStore(
    role_dsn("obsidian_exchange_bot_background", "synthetic-background-only"),
    role_dsn("obsidian_exchange_bot_delivery", "synthetic-delivery-only"),
    role_dsn("obsidian_exchange_bot_transport", "synthetic-transport-only"),
)

with psycopg.connect(role_dsn("obsidian_exchange_bot_policy_approver", "synthetic-approver-only")) as approver:
    approval = approver.execute("SELECT bot_b60_approve_policy(%s,7,%s,%s)", (policy_id, digest, "c" * 64)).fetchone()[0]
    assert approver.execute("SELECT bot_b60_approve_policy(%s,7,%s,%s)", (policy_id, digest, "c" * 64)).fetchone()[0] == approval
    activation = approver.execute("SELECT bot_b60_activate_policy(%s,7,%s,NULL,%s)", (policy_id, approval, "d" * 64)).fetchone()[0]
    assert approver.execute("SELECT bot_b60_activate_policy(%s,7,%s,NULL,%s)", (policy_id, approval, "d" * 64)).fetchone()[0] == activation

with psycopg.connect(dsn) as db:
    db.execute(
        "INSERT INTO bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts) VALUES"
        "('montera_admin','1:9001','{\"user_id\":101}',9001,%s,7,clock_timestamp(),4),"
        "('montera_admin','1:9002','{\"user_id\":101}',9002,%s,7,clock_timestamp(),4)",
        (policy_id, policy_id),
    )

with psycopg.connect(role_dsn("obsidian_exchange_bot_reconciler", "synthetic-reconciler-only")) as reconciler:
    event = reconciler.execute("SELECT bot_b60_set_recipient_revocation(9001,'REVOKE',NULL,'ACCOUNT_COMPROMISED',%s)", ("e" * 64,)).fetchone()[0]
    assert reconciler.execute("SELECT bot_b60_set_recipient_revocation(9001,'REVOKE',%s,'ACCOUNT_COMPROMISED',%s)", (event, "e" * 64)).fetchone()[0] == event

claimed = adapter.claim_notification(kind="montera_admin")
assert claimed["recipient_id"] == 9002
correlation = str(__import__("uuid").uuid4())
assert adapter.pre_submit(claimed["id"], attempt_token=claimed["attempt_token"], client_correlation_id=correlation) == "ALLOW"
assert adapter.pre_submit(claimed["id"], attempt_token=claimed["attempt_token"], client_correlation_id=correlation) == "ALLOW"

with psycopg.connect(role_dsn("obsidian_exchange_bot_reconciler", "synthetic-reconciler-only")) as reconciler:
    event_2 = reconciler.execute("SELECT bot_b60_set_recipient_revocation(9002,'REVOKE',NULL,'ACCESS_REVOKED',%s)", ("f" * 64,)).fetchone()[0]
    restored = reconciler.execute("SELECT bot_b60_set_recipient_revocation(9002,'RESTORE',%s,'FALSE_POSITIVE_RESTORE',%s)", (event_2, "a" * 64)).fetchone()[0]
    assert restored != event_2
    assert reconciler.execute(
        "SELECT bot_b60_set_recipient_revocation(5000000000,'REVOKE',NULL,'ACCESS_REVOKED',%s) IS NOT NULL",
        ("8" * 64,),
    ).fetchone() == (True,)
assert adapter.pre_submit(
    claimed["id"], attempt_token=claimed["attempt_token"],
    client_correlation_id=correlation,
) == "DENY_REVOKED"

observed = datetime.now(timezone.utc)
evidence = adapter.record_delivery_evidence(
    claimed["id"], attempt_token=claimed["attempt_token"], client_correlation_id=correlation,
    outcome="UNCERTAIN",
    provider_request_id=None, provider_message_id=None, reason_code="TRANSPORT_UNCERTAIN",
    response_sha256="9" * 64, observed_at=observed,
)
assert evidence is not None
assert adapter.mark_notification_manual(
    claimed["id"], attempt_token=claimed["attempt_token"], evidence_id=evidence)

with psycopg.connect(dsn) as db:
    db.execute(
        "INSERT INTO bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts) "
        "VALUES('recall','accepted-recovery','{\"user_id\":9003}',9003,%s,7,clock_timestamp(),4)",
        (policy_id,),
    )
accepted = adapter.claim_notification(kind="recall")
accepted_correlation = str(__import__("uuid").uuid4())
assert adapter.pre_submit(accepted["id"], attempt_token=accepted["attempt_token"],
                          client_correlation_id=accepted_correlation) == "ALLOW"
accepted_evidence = adapter.record_delivery_evidence(
    accepted["id"], attempt_token=accepted["attempt_token"],
    client_correlation_id=accepted_correlation, outcome="ACCEPTED",
    provider_request_id=None, provider_message_id="44", reason_code=None,
    response_sha256="7" * 64, observed_at=datetime.now(timezone.utc),
)
notification_reconciler_dsn = role_dsn("obsidian_exchange_bot_notification_reconciler",
                                       "synthetic-notification-reconciler-only")
def reconcile_once(_):
    with psycopg.connect(notification_reconciler_dsn) as reconciler:
        return reconciler.execute("SELECT bot_b62_reconcile_accepted(10)").fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as pool:
    assert sum(pool.map(reconcile_once, range(8))) == 1
assert reconcile_once(0) == 0

with psycopg.connect(dsn) as db:
    db.execute(
        "INSERT INTO bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts) VALUES"
        "('recall','stale-preauth','{\"user_id\":9004}',9004,%s,7,clock_timestamp(),4),"
        "('recall','stale-authorized','{\"user_id\":9005}',9005,%s,7,clock_timestamp(),4)",
        (policy_id, policy_id),
    )
preauth = adapter.claim_notification(kind="recall")
authorized = adapter.claim_notification(kind="recall")
if preauth["recipient_id"] == 9005:
    preauth, authorized = authorized, preauth
authorized_correlation = str(__import__("uuid").uuid4())
assert adapter.pre_submit(
    authorized["id"], attempt_token=authorized["attempt_token"],
    client_correlation_id=authorized_correlation,
) == "ALLOW"
with psycopg.connect(dsn) as db:
    db.execute(
        "UPDATE bot_notification_jobs SET claimed_at=clock_timestamp()-interval '20 minutes' "
        "WHERE id IN(%s,%s)", (preauth["id"], authorized["id"]),
    )
    db.execute(
        "UPDATE bot_notification_delivery_attempts SET claimed_at=clock_timestamp()-interval '20 minutes' "
        "WHERE job_id IN(%s,%s)", (preauth["id"], authorized["id"]),
    )

def reconcile_b63(_):
    with psycopg.connect(notification_reconciler_dsn) as reconciler:
        return reconciler.execute("SELECT bot_b63_reconcile_batch(10,60)").fetchone()[0]
with ThreadPoolExecutor(max_workers=8) as pool:
    stale_results = list(pool.map(reconcile_b63, range(8)))
assert sum(result["staleManualReview"] for result in stale_results) == 2
assert reconcile_b63(0)["staleManualReview"] == 0

# Inject a failure after the immutable review insert but before the job
# transition. The transaction must preserve both old state and absence of audit.
with psycopg.connect(dsn) as db:
    db.execute(
        "INSERT INTO bot_notification_jobs(kind,dedupe_key,payload,recipient_id,policy_id,policy_version,eligibility_at,max_attempts) "
        "VALUES('recall','stale-fault','{\"user_id\":9006}',9006,%s,7,clock_timestamp(),4)",
        (policy_id,),
    )
faulted = adapter.claim_notification(kind="recall")
with psycopg.connect(dsn) as db:
    db.execute(
        "UPDATE bot_notification_jobs SET claimed_at=clock_timestamp()-interval '20 minutes' WHERE id=%s",
        (faulted["id"],),
    )
    db.execute(
        "UPDATE bot_notification_delivery_attempts SET claimed_at=clock_timestamp()-interval '20 minutes' WHERE job_id=%s",
        (faulted["id"],),
    )
    db.commit()
    db.execute(
        "CREATE FUNCTION pg_temp.reject_b63_transition() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN "
        "IF NEW.manual_reason_code LIKE 'STALE_%' THEN RAISE EXCEPTION 'synthetic_b63_fault';END IF;RETURN NEW;END$$;"
        "CREATE TRIGGER synthetic_b63_fault BEFORE UPDATE ON bot_notification_jobs "
        "FOR EACH ROW EXECUTE FUNCTION pg_temp.reject_b63_transition()"
    )
    try:
        db.execute("SELECT bot_b63_reconcile_batch(10,60)")
    except psycopg.errors.RaiseException as exc:
        assert "synthetic_b63_fault" in str(exc)
        db.rollback()
    else:
        raise AssertionError("synthetic stale transition fault did not fire")
with psycopg.connect(dsn) as db:
    assert db.execute("SELECT state FROM bot_notification_jobs WHERE id=%s", (faulted["id"],)).fetchone() == ("sending",)
    assert db.execute("SELECT count(*) FROM bot_notification_stale_attempt_reviews WHERE job_id=%s", (faulted["id"],)).fetchone() == (0,)
assert reconcile_b63(0)["staleManualReview"] == 1

with psycopg.connect(dsn) as db:
    assert db.execute("SELECT state,attempt_token IS NULL FROM bot_notification_jobs WHERE recipient_id=9001").fetchone() == ("quarantined", True)
    assert db.execute("SELECT prior_state,possible_in_flight FROM bot_notification_recipient_quarantines").fetchone() == ("pending", False)
    assert db.execute("SELECT state FROM bot_notification_jobs WHERE recipient_id=9002").fetchone() == ("manual",)
    assert db.execute("SELECT prior_state,possible_in_flight FROM bot_notification_recipient_quarantines WHERE job_id=(SELECT id FROM bot_notification_jobs WHERE recipient_id=9002)").fetchone() == ("sending", True)
    assert db.execute("SELECT client_correlation_id::text FROM bot_notification_submit_authorizations").fetchone() == (correlation,)
    assert db.execute("SELECT state FROM bot_notification_jobs WHERE id=%s", (accepted["id"],)).fetchone() == ("sent",)
    assert db.execute(
        "SELECT classification,submit_authorization_id IS NOT NULL FROM bot_notification_stale_attempt_reviews "
        "WHERE job_id IN(%s,%s) ORDER BY classification",
        (preauth["id"], authorized["id"]),
    ).fetchall() == [
        ("AUTHORIZED_NO_TERMINAL_EVIDENCE", True),
        ("PRE_SUBMIT_ABANDONED", False),
    ]
    assert db.execute(
        "SELECT count(*) FROM bot_notification_jobs WHERE id IN(%s,%s) AND state='manual'",
        (preauth["id"], authorized["id"]),
    ).fetchone() == (2,)
    assert db.execute("SELECT provider_request_id,client_correlation_id::text FROM bot_notification_delivery_evidence WHERE evidence_id=%s",
                      (accepted_evidence,)).fetchone() == (None, accepted_correlation)
    assert db.execute("SELECT approver_principal FROM bot_notification_policy_approvals").fetchone() == ("obsidian_exchange_bot_policy_approver",)
    assert db.execute("SELECT actor_principal FROM bot_notification_recipient_revocation_events").fetchone() == ("obsidian_exchange_bot_reconciler",)
    assert db.execute(
        "SELECT has_table_privilege('obsidian_exchange_bot_policy_approver','bot_notification_policy_approvals','SELECT'),"
        "has_table_privilege('obsidian_exchange_bot_reconciler','bot_notification_recipient_revocations','UPDATE'),"
        "has_function_privilege('obsidian_exchange_bot','bot_b60_approve_policy(uuid,bigint,text,text)','EXECUTE')"
    ).fetchone() == (False, False, False)
    assert db.execute(
        "SELECT has_function_privilege('obsidian_exchange_bot_delivery','bot_b53_delivery_mark_sent(bigint,uuid,uuid)','EXECUTE'),"
        "has_function_privilege('obsidian_exchange_bot_delivery','bot_b62_consume_accepted(bigint,uuid,uuid)','EXECUTE'),"
        "has_function_privilege('obsidian_exchange_bot_transport','bot_b53_transport_record_evidence(bigint,uuid,text,text,text,text,text,timestamptz)','EXECUTE'),"
        "has_function_privilege('obsidian_exchange_bot_transport','bot_b62_transport_record_evidence(bigint,uuid,uuid,text,text,text,text,text,timestamptz)','EXECUTE')"
    ).fetchone() == (False, True, False, True)

print("E0.3 B5.3 authenticated governance, monotonic activation and recipient quarantine: OK")
