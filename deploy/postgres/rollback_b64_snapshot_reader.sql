-- Transactional rollback for provision_b64_snapshot_reader.sql.
-- DROP ROLE deliberately fails closed if an undeclared dependency exists.
BEGIN;
SET LOCAL statement_timeout = '30s';
SET LOCAL lock_timeout = '5s';
SET LOCAL search_path = pg_catalog;

DO $rollback$
DECLARE
    expected_database text :=
      current_setting('obsidian.snapshot_reader_expected_database', true);
    deployment_nonce text :=
      current_setting('obsidian.snapshot_reader_deployment_nonce', true);
    schema_name text;
    table_record record;
BEGIN
    IF expected_database IS NULL OR expected_database <> current_database()
       OR (current_database() <> 'obsidian_exchange'
           AND current_database() !~ '^b64_reader_contract_[0-9]+$') THEN
        RAISE EXCEPTION 'refusing unexpected snapshot source database: %',
                        current_database();
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles
                    WHERE rolname = 'obsidian_b64_snapshot_reader') THEN
        RETURN;
    END IF;
    IF deployment_nonce IS NULL OR deployment_nonce !~ '^[0-9a-f]{32}$'
       OR COALESCE(shobj_description(
              (SELECT oid FROM pg_roles
                WHERE rolname = 'obsidian_b64_snapshot_reader'),
              'pg_authid'), '') <>
          'obsidian-b64-snapshot-reader-dormant-v1:' || deployment_nonce THEN
        RAISE EXCEPTION 'refusing rollback with deployment binding mismatch';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_roles
         WHERE rolname = 'obsidian_b64_snapshot_reader'
           AND (rolsuper OR rolcreatedb OR rolcreaterole OR rolreplication
                OR rolbypassrls)
    ) THEN
        RAISE EXCEPTION 'refusing rollback of elevated snapshot reader role';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_auth_members m
         WHERE m.member = (SELECT oid FROM pg_roles
                            WHERE rolname = 'obsidian_b64_snapshot_reader')
            OR m.roleid = (SELECT oid FROM pg_roles
                            WHERE rolname = 'obsidian_b64_snapshot_reader')
    ) THEN
        RAISE EXCEPTION 'refusing rollback with snapshot reader membership';
    END IF;
    IF EXISTS (
        SELECT 1 FROM pg_shdepend
         WHERE refclassid = 'pg_authid'::regclass
           AND refobjid = (SELECT oid FROM pg_roles
                            WHERE rolname = 'obsidian_b64_snapshot_reader')
           AND deptype = 'o'
    ) THEN
        RAISE EXCEPTION 'refusing rollback while snapshot reader owns objects';
    END IF;

    EXECUTE format('REVOKE ALL ON DATABASE %I '
                   'FROM obsidian_b64_snapshot_reader', current_database());
    FOR schema_name IN
        SELECT nspname FROM pg_namespace
         WHERE nspname <> 'information_schema' AND nspname !~ '^pg_'
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
    ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator IN SCHEMA public
      REVOKE ALL ON TABLES FROM obsidian_b64_snapshot_reader;
    ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator IN SCHEMA public
      REVOKE ALL ON SEQUENCES FROM obsidian_b64_snapshot_reader;
    ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_migrator
      REVOKE ALL ON FUNCTIONS FROM obsidian_b64_snapshot_reader;
    DROP ROLE obsidian_b64_snapshot_reader;
END
$rollback$;

COMMIT;
