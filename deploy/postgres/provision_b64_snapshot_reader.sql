-- Exact least-privilege source principal for the frozen 001-023 B64 snapshot.
--
-- Run as a PostgreSQL cluster administrator while connected to the source
-- database.  No password is created or changed here: credential material is a
-- separate secret-management operation.  Reapplying this file is safe only
-- while the database still has the exact frozen 54/29/2 object inventory.
BEGIN;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL search_path = pg_catalog;

DO $profile$
DECLARE
    expected_database text :=
      current_setting('obsidian.snapshot_reader_expected_database', true);
    require_absent boolean := COALESCE(
      current_setting('obsidian.snapshot_reader_require_absent', true), 'off'
    ) = 'on';
    deployment_nonce text :=
      current_setting('obsidian.snapshot_reader_deployment_nonce', true);
    expected_comment text;
    expected_tables text[] := ARRAY[
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
    actual_tables text[];
    actual_sequences text[];
    actual_functions text[];
    actual_column_count bigint;
    actual_catalog_sha256 text;
    qualified text;
    table_record record;
BEGIN
    IF expected_database IS NULL OR expected_database <> current_database()
       OR (current_database() <> 'obsidian_exchange'
           AND current_database() !~ '^b64_reader_contract_[0-9]+$') THEN
        RAISE EXCEPTION 'refusing unexpected snapshot source database: %',
                        current_database();
    END IF;
    IF deployment_nonce IS NULL
       OR deployment_nonce !~ '^[0-9a-f]{32}$' THEN
        RAISE EXCEPTION 'invalid snapshot reader deployment nonce';
    END IF;
    expected_comment := 'obsidian-b64-snapshot-reader-dormant-v1:'
                        || deployment_nonce;

    SELECT array_agg(c.relname ORDER BY c.relname)
      INTO actual_tables
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p');
    IF COALESCE(cardinality(actual_tables), 0) <> cardinality(expected_tables)
       OR NOT (actual_tables @> expected_tables
               AND expected_tables @> actual_tables) THEN
        RAISE EXCEPTION
          'snapshot reader requires exact frozen 001-023 table inventory';
    END IF;

    SELECT count(*),
           pg_catalog.encode(pg_catalog.sha256(pg_catalog.convert_to(
             COALESCE(pg_catalog.jsonb_agg(pg_catalog.jsonb_build_object(
               'table', c.relname, 'column', a.attname, 'number', a.attnum,
               'type', pg_catalog.format_type(a.atttypid, a.atttypmod),
               'notNull', a.attnotnull, 'identity', a.attidentity::text,
               'generated', a.attgenerated::text,
               'default', pg_catalog.pg_get_expr(d.adbin, d.adrelid, false),
               'collation', CASE WHEN a.attcollation = 0 THEN NULL
                 ELSE cn.nspname || '.' || coll.collname END
             ) ORDER BY c.relname COLLATE "C", a.attnum),
             '[]'::jsonb)::text, 'UTF8')),
             'hex')
      INTO actual_column_count, actual_catalog_sha256
      FROM pg_catalog.pg_class c
      JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
      JOIN pg_catalog.pg_attribute a ON a.attrelid = c.oid
      LEFT JOIN pg_catalog.pg_attrdef d
        ON d.adrelid = a.attrelid AND d.adnum = a.attnum
      LEFT JOIN pg_catalog.pg_collation coll ON coll.oid = a.attcollation
      LEFT JOIN pg_catalog.pg_namespace cn ON cn.oid = coll.collnamespace
     WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
       AND a.attnum > 0 AND NOT a.attisdropped;
    IF actual_column_count <> 423
       OR actual_catalog_sha256 <>
          'adf9ef068c9778f3173bac3d824606ab4796b67f5647df770cbbc8be4ad53f99' THEN
        RAISE EXCEPTION
          'snapshot reader requires exact frozen 001-023 column catalog';
    END IF;

    SELECT array_agg(c.relname ORDER BY c.relname)
      INTO actual_sequences
      FROM pg_class c
      JOIN pg_namespace n ON n.oid = c.relnamespace
     WHERE n.nspname = 'public' AND c.relkind = 'S';
    IF COALESCE(cardinality(actual_sequences), 0)
         <> cardinality(expected_sequences)
       OR NOT (actual_sequences @> expected_sequences
               AND expected_sequences @> actual_sequences) THEN
        RAISE EXCEPTION
          'snapshot reader requires exact frozen 001-023 sequence inventory';
    END IF;

    SELECT array_agg(
               p.proname || '(' || pg_get_function_identity_arguments(p.oid)
               || ')' ORDER BY p.proname,
               pg_get_function_identity_arguments(p.oid))
      INTO actual_functions
      FROM pg_proc p
      JOIN pg_namespace n ON n.oid = p.pronamespace
     WHERE n.nspname = 'public';
    IF COALESCE(cardinality(actual_functions), 0)
         <> cardinality(expected_functions)
       OR NOT (actual_functions @> expected_functions
               AND expected_functions @> actual_functions) THEN
        RAISE EXCEPTION
          'snapshot reader requires exact frozen 001-023 function inventory';
    END IF;

    IF EXISTS (
        SELECT 1
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('v', 'm', 'f')
    ) THEN
        RAISE EXCEPTION 'snapshot reader refuses unexpected public relations';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
           AND c.relrowsecurity
    ) THEN
        RAISE EXCEPTION 'snapshot reader refuses row-level security tables';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_largeobject_metadata) THEN
        RAISE EXCEPTION 'snapshot reader refuses databases with large objects';
    END IF;
    IF pg_get_userbyid((SELECT datdba FROM pg_database
                         WHERE datname = current_database()))
         <> 'obsidian_migrator'
       OR pg_get_userbyid((SELECT nspowner FROM pg_namespace
                            WHERE nspname = 'public'))
         <> 'obsidian_migrator'
       OR EXISTS (
          SELECT 1
            FROM pg_class c
            JOIN pg_namespace n ON n.oid = c.relnamespace
           WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p', 'S')
             AND pg_get_userbyid(c.relowner) <> 'obsidian_migrator')
       OR EXISTS (
          SELECT 1
            FROM pg_proc p
            JOIN pg_namespace n ON n.oid = p.pronamespace
           WHERE n.nspname = 'public'
             AND pg_get_userbyid(p.proowner) <> 'obsidian_migrator') THEN
        RAISE EXCEPTION 'snapshot reader requires obsidian_migrator ownership';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM pg_roles
                    WHERE rolname = 'obsidian_migrator') THEN
        RAISE EXCEPTION 'required role is missing: obsidian_migrator';
    END IF;

    IF require_absent AND EXISTS (SELECT 1 FROM pg_roles
                                  WHERE rolname =
                                        'obsidian_b64_snapshot_reader') THEN
        RAISE EXCEPTION 'snapshot reader role must be absent for first apply';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles
                    WHERE rolname = 'obsidian_b64_snapshot_reader') THEN
        CREATE ROLE obsidian_b64_snapshot_reader NOLOGIN NOINHERIT
          NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
          CONNECTION LIMIT 2;
        EXECUTE format('COMMENT ON ROLE obsidian_b64_snapshot_reader IS %L',
                       expected_comment);
    ELSIF COALESCE(shobj_description(
              (SELECT oid FROM pg_roles
                WHERE rolname = 'obsidian_b64_snapshot_reader'),
              'pg_authid'), '') <> expected_comment THEN
        RAISE EXCEPTION 'snapshot reader deployment binding mismatch';
    END IF;

    IF EXISTS (
        SELECT 1 FROM pg_roles
         WHERE rolname = 'obsidian_b64_snapshot_reader'
           AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication
                OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'refusing elevated snapshot reader role';
    END IF;
    IF EXISTS (
        SELECT 1
          FROM pg_auth_members m
         WHERE m.member = (SELECT oid FROM pg_roles
                            WHERE rolname = 'obsidian_b64_snapshot_reader')
            OR m.roleid = (SELECT oid FROM pg_roles
                            WHERE rolname = 'obsidian_b64_snapshot_reader')
    ) THEN
        RAISE EXCEPTION 'snapshot reader participates in role membership';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_authid
         WHERE rolname = 'obsidian_b64_snapshot_reader'
           AND (rolpassword IS NOT NULL OR rolvaliduntil IS NOT NULL)
    ) THEN
        RAISE EXCEPTION 'snapshot reader has pre-existing credential state';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_db_role_setting
         WHERE setrole = (SELECT oid FROM pg_roles
                           WHERE rolname = 'obsidian_b64_snapshot_reader')
           AND setdatabase <> 0
    ) THEN
        RAISE EXCEPTION 'snapshot reader has per-database settings';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_shdepend
         WHERE refclassid = 'pg_authid'::regclass
           AND refobjid = (SELECT oid FROM pg_roles
                            WHERE rolname = 'obsidian_b64_snapshot_reader')
           AND deptype = 'o'
    ) THEN
        RAISE EXCEPTION 'snapshot reader owns database objects';
    END IF;

    ALTER ROLE obsidian_b64_snapshot_reader NOLOGIN NOINHERIT
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS
      CONNECTION LIMIT 2;
    ALTER ROLE obsidian_b64_snapshot_reader RESET ALL;
    ALTER ROLE obsidian_b64_snapshot_reader SET search_path = pg_catalog;
    ALTER ROLE obsidian_b64_snapshot_reader
      SET default_transaction_read_only = on;
    ALTER ROLE obsidian_b64_snapshot_reader
      SET default_transaction_isolation = 'repeatable read';
    ALTER ROLE obsidian_b64_snapshot_reader SET statement_timeout = '180s';
    ALTER ROLE obsidian_b64_snapshot_reader SET lock_timeout = '5s';
    ALTER ROLE obsidian_b64_snapshot_reader
      SET idle_in_transaction_session_timeout = '210s';
    ALTER ROLE obsidian_b64_snapshot_reader SET row_security = off;

    EXECUTE format('REVOKE ALL ON DATABASE %I '
                   'FROM obsidian_b64_snapshot_reader', current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I '
                   'TO obsidian_b64_snapshot_reader', current_database());
    REVOKE ALL ON SCHEMA public FROM obsidian_b64_snapshot_reader;
    GRANT USAGE ON SCHEMA public TO obsidian_b64_snapshot_reader;
    REVOKE ALL ON ALL TABLES IN SCHEMA public
      FROM obsidian_b64_snapshot_reader;
    -- Table-level REVOKE does not remove a reused role's column ACLs.
    FOR table_record IN
        SELECT c.relname,
               string_agg(format('%I', a.attname), ', ' ORDER BY a.attnum)
                 AS columns
          FROM pg_class c
          JOIN pg_namespace n ON n.oid = c.relnamespace
          JOIN pg_attribute a ON a.attrelid = c.oid
         WHERE n.nspname = 'public' AND c.relkind IN ('r', 'p')
           AND a.attnum > 0 AND NOT a.attisdropped
         GROUP BY c.relname
         ORDER BY c.relname
    LOOP
        EXECUTE format('REVOKE ALL (%s) ON TABLE %I.%I '
                       'FROM obsidian_b64_snapshot_reader',
                       table_record.columns, 'public', table_record.relname);
    END LOOP;
    REVOKE ALL ON ALL SEQUENCES IN SCHEMA public
      FROM obsidian_b64_snapshot_reader;
    REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public
      FROM obsidian_b64_snapshot_reader;

    SELECT string_agg(format('%I.%I', 'public', name), ', ')
      INTO qualified FROM unnest(expected_tables) AS name;
    EXECUTE 'GRANT SELECT ON TABLE ' || qualified
            || ' TO obsidian_b64_snapshot_reader';
    SELECT string_agg(format('%I.%I', 'public', name), ', ')
      INTO qualified FROM unnest(expected_sequences) AS name;
    -- pg_dump reads last_value/is_called.  SELECT is required for a complete
    -- archive; USAGE and UPDATE remain absent, so nextval/setval are denied.
    EXECUTE 'GRANT SELECT ON SEQUENCE ' || qualified
            || ' TO obsidian_b64_snapshot_reader';

    ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator IN SCHEMA public
      REVOKE ALL ON TABLES FROM obsidian_b64_snapshot_reader;
    ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator IN SCHEMA public
      REVOKE ALL ON SEQUENCES FROM obsidian_b64_snapshot_reader;
    ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator
      REVOKE ALL ON FUNCTIONS FROM obsidian_b64_snapshot_reader;
END
$profile$;

-- A reused role must not retain access in another user-created schema in this
-- database.  System catalogs remain readable only to PostgreSQL's normal
-- built-in extent and are not grant targets here.
DO $other_schemas$
DECLARE
    schema_name text;
    table_record record;
BEGIN
    FOR schema_name IN
        SELECT nspname FROM pg_namespace
         WHERE nspname <> 'public'
           AND nspname <> 'information_schema'
           AND nspname !~ '^pg_'
         ORDER BY nspname
    LOOP
        EXECUTE format('REVOKE ALL ON ALL TABLES IN SCHEMA %I '
                       'FROM obsidian_b64_snapshot_reader', schema_name);
        FOR table_record IN
            SELECT c.relname,
                   string_agg(format('%I', a.attname), ', ' ORDER BY a.attnum)
                     AS columns
              FROM pg_class c
              JOIN pg_attribute a ON a.attrelid = c.oid
             WHERE c.relnamespace = (
                       SELECT oid FROM pg_namespace WHERE nspname = schema_name)
               AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
               AND a.attnum > 0 AND NOT a.attisdropped
             GROUP BY c.relname
             ORDER BY c.relname
        LOOP
            EXECUTE format('REVOKE ALL (%s) ON TABLE %I.%I '
                           'FROM obsidian_b64_snapshot_reader',
                           table_record.columns, schema_name,
                           table_record.relname);
        END LOOP;
        EXECUTE format('REVOKE ALL ON ALL SEQUENCES IN SCHEMA %I '
                       'FROM obsidian_b64_snapshot_reader', schema_name);
        EXECUTE format('REVOKE ALL ON ALL FUNCTIONS IN SCHEMA %I '
                       'FROM obsidian_b64_snapshot_reader', schema_name);
        EXECUTE format('REVOKE ALL ON SCHEMA %I '
                       'FROM obsidian_b64_snapshot_reader', schema_name);
    END LOOP;
END
$other_schemas$;

COMMIT;
