-- Least-privilege runtime ACLs after migrations 001-023.
--
-- Apply as the database/schema owner after every schema migration.  New
-- objects intentionally receive no runtime grants until this matrix is
-- reviewed and this file is updated/reapplied.
BEGIN;

-- This matrix is intentionally scoped to the production 001-023 schema.  A
-- later numbered migration must receive a separately reviewed ACL profile;
-- never let the blanket grants below absorb a new relation by accident.
DO $inventory$
DECLARE
    expected text[] := ARRAY[
        'orders', 'web_users', 'web_sessions', 'bot_users', 'workers',
        'worker_ids', 'operators', 'blocked_users', 'blocked_addresses',
        'reserves', 'system_flags', 'admin_log', 'risk_events',
        'user_vip_volume', 'rate_subscriptions', 'referral_bonuses',
        'client_address_notes', 'reviews', 'payout_queue', 'payout_shadow',
        'provider_health', 'provider_attempts', 'alert_throttle',
        'alert_watermark', 'audit_log', 'referrals', 'referral_addresses',
        'rate_locks', 'promo_codes', 'promo_uses', 'payment_sessions',
        'payment_transition_audit', 'payment_notification_outbox',
        'gift_vouchers', 'dca_schedules', 'limit_orders', 'support_tickets',
        'support_messages', 'swap_sessions', 'sell_orders', 'order_receipts',
        'sent_notifications', 'wallet_links', 'wallet_send_intents',
        'payout_intents', 'payout_intent_audit', 'payout_reconciliations',
        'referral_payout_intents', 'referral_payout_intent_audit',
        'notification_outbox', 'order_lifecycle_work',
        'sell_settlement_ledger', 'sell_settlement_outbox',
        'bot_notification_jobs'
    ];
    expected_sequences text[] := ARRAY[
        'admin_log_id_seq', 'audit_log_id_seq',
        'bot_notification_jobs_id_seq', 'dca_schedules_id_seq',
        'gift_vouchers_id_seq', 'limit_orders_id_seq',
        'notification_outbox_id_seq', 'order_lifecycle_work_id_seq',
        'orders_order_id_seq', 'payment_notification_outbox_id_seq',
        'payment_sessions_id_seq', 'payment_transition_audit_id_seq',
        'payout_intent_audit_id_seq', 'payout_intents_id_seq',
        'payout_queue_id_seq', 'promo_codes_id_seq', 'rate_locks_id_seq',
        'referral_bonuses_id_seq', 'referral_payout_intent_audit_id_seq',
        'referral_payout_intents_id_seq', 'reviews_id_seq',
        'risk_events_id_seq', 'sell_orders_id_seq',
        'sell_settlement_outbox_id_seq', 'support_messages_id_seq',
        'support_tickets_id_seq', 'swap_sessions_id_seq',
        'wallet_send_intents_id_seq', 'web_users_id_seq'
    ];
    expected_functions text[] := ARRAY[
        'claim_next_order_payout()', 'claim_next_referral_payout()'
    ];
    actual text[];
    actual_sequences text[];
    actual_functions text[];
BEGIN
    SELECT array_agg(c.relname ORDER BY c.relname)
      INTO actual
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p');
    IF cardinality(actual) <> cardinality(expected)
       OR NOT (actual @> expected AND expected @> actual) THEN
        RAISE EXCEPTION 'runtime privilege matrix requires exact 001-023 table inventory';
    END IF;
    SELECT array_agg(c.relname ORDER BY c.relname)
      INTO actual_sequences
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'S';
    IF cardinality(actual_sequences) <> cardinality(expected_sequences)
       OR NOT (actual_sequences @> expected_sequences
               AND expected_sequences @> actual_sequences) THEN
        RAISE EXCEPTION 'runtime privilege matrix requires exact 001-023 sequence inventory';
    END IF;
    SELECT array_agg(
               p.proname || '(' || pg_get_function_identity_arguments(p.oid) || ')'
               ORDER BY p.proname, pg_get_function_identity_arguments(p.oid)
           )
      INTO actual_functions
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public';
    IF cardinality(actual_functions) <> cardinality(expected_functions)
       OR NOT (actual_functions @> expected_functions
               AND expected_functions @> actual_functions) THEN
        RAISE EXCEPTION 'runtime privilege matrix requires exact 001-023 function inventory';
    END IF;
END
$inventory$;

DO $roles$
DECLARE
    role_name text;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'obsidian_migrator',
        'obsidian_app',
        'obsidian_readonly',
        'obsidian_payout'
    ]
    LOOP
        IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = role_name) THEN
            RAISE EXCEPTION 'required role is missing: %', role_name;
        END IF;
    END LOOP;
END
$roles$;

-- PostgreSQL defaults allow every role to CONNECT/TEMP and to EXECUTE new
-- functions.  Remove those ambient privileges before granting the matrix.
DO $database_acl$
BEGIN
    EXECUTE format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC',
                   current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO obsidian_migrator, '
                   'obsidian_app, obsidian_readonly, obsidian_payout',
                   current_database());
END
$database_acl$;

REVOKE ALL ON SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC;

-- Revoke first so reapplying this file also removes stale/broader grants.
REVOKE ALL ON ALL TABLES IN SCHEMA public
  FROM obsidian_app, obsidian_readonly, obsidian_payout;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public
  FROM obsidian_app, obsidian_readonly, obsidian_payout;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public
  FROM obsidian_app, obsidian_readonly, obsidian_payout;

GRANT USAGE ON SCHEMA public
  TO obsidian_app, obsidian_readonly, obsidian_payout;

-- Bot, relay, notifier and monitor share one authoritative runtime boundary.
-- They need ordinary DML but never DDL, TRUNCATE, REFERENCES or TRIGGER.
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public
  TO obsidian_app;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO obsidian_app;

-- Laravel, monitor and support-bot share the read-only role. Their combined
-- dashboards and health checks span the authoritative inventory, but the role
-- is transaction-read-only and receives no sequence/function/write rights.
GRANT SELECT ON ALL TABLES IN SCHEMA public TO obsidian_readonly;

-- The isolated signer consumer may only claim and finish immutable payout
-- intents.  It cannot create a debt, change its destination/amount, reconcile
-- an order, write audit/outbox rows, or inspect customer/order tables.
GRANT SELECT ON TABLE payout_intents, referral_payout_intents
  TO obsidian_payout;
GRANT UPDATE (
  state, attempts, txid, error_code, claimed_at, finished_at, updated_at
) ON payout_intents TO obsidian_payout;
GRANT UPDATE (
  state, attempts, txid, error_code, claimed_at, finished_at, updated_at
) ON referral_payout_intents TO obsidian_payout;
GRANT EXECUTE ON FUNCTION claim_next_order_payout() TO obsidian_payout;
GRANT EXECUTE ON FUNCTION claim_next_referral_payout() TO obsidian_payout;

-- Future objects stay fail-closed.  Rerun this file only after adding them to
-- the explicit matrix (worker/read-only) or approving app DML.
ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator IN SCHEMA public
  REVOKE ALL ON TABLES FROM PUBLIC;
ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator IN SCHEMA public
  REVOKE ALL ON SEQUENCES FROM PUBLIC;
-- Function EXECUTE is granted to PUBLIC by the global built-in default.
-- PostgreSQL cannot remove that global grant with a per-schema REVOKE, so this
-- one default privilege must deliberately omit IN SCHEMA.
ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator
  REVOKE EXECUTE ON FUNCTIONS FROM PUBLIC;

COMMIT;
