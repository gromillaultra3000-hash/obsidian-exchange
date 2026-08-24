-- Cluster roles for the ObsidianExchange PostgreSQL boundary.
--
-- Run once as a PostgreSQL cluster administrator.  Passwords are deliberately
-- absent: provision each LOGIN credential from a root-owned secret after this
-- file succeeds.  A pre-existing elevated role is treated as a configuration
-- error instead of being silently downgraded.
DO $roles$
DECLARE
    role_name text;
    role_record record;
BEGIN
    FOREACH role_name IN ARRAY ARRAY[
        'obsidian_migrator',
        'obsidian_app',
        'obsidian_readonly',
        'obsidian_payout'
    ]
    LOOP
        SELECT rolname, rolsuper, rolcreatedb, rolcreaterole, rolreplication,
               rolbypassrls
          INTO role_record
          FROM pg_roles
         WHERE rolname = role_name;

        IF NOT FOUND THEN
            EXECUTE format(
                'CREATE ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOREPLICATION NOBYPASSRLS INHERIT',
                role_name
            );
        ELSIF role_record.rolsuper
           OR role_record.rolcreatedb
           OR role_record.rolcreaterole
           OR role_record.rolreplication
           OR role_record.rolbypassrls THEN
            RAISE EXCEPTION 'refusing elevated runtime role: %', role_name;
        ELSE
            EXECUTE format(
                'ALTER ROLE %I LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE '
                'NOREPLICATION NOBYPASSRLS INHERIT',
                role_name
            );
        END IF;

        IF EXISTS (
            SELECT 1
              FROM pg_auth_members membership
             WHERE membership.member = (
                 SELECT oid FROM pg_roles WHERE rolname = role_name
             )
                OR membership.roleid = (
                 SELECT oid FROM pg_roles WHERE rolname = role_name
             )
        ) THEN
            RAISE EXCEPTION 'runtime role participates in membership: %', role_name;
        END IF;
    END LOOP;
END
$roles$;

ALTER ROLE obsidian_migrator CONNECTION LIMIT 2;
ALTER ROLE obsidian_app CONNECTION LIMIT 60;
ALTER ROLE obsidian_readonly CONNECTION LIMIT 10;
ALTER ROLE obsidian_payout CONNECTION LIMIT 4;

ALTER ROLE obsidian_migrator SET search_path = public, pg_catalog;
ALTER ROLE obsidian_app SET search_path = public, pg_catalog;
ALTER ROLE obsidian_readonly SET search_path = public, pg_catalog;
ALTER ROLE obsidian_payout SET search_path = public, pg_catalog;

ALTER ROLE obsidian_app SET statement_timeout = '15s';
ALTER ROLE obsidian_app SET lock_timeout = '3s';
ALTER ROLE obsidian_app SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE obsidian_readonly SET default_transaction_read_only = on;
ALTER ROLE obsidian_readonly SET statement_timeout = '15s';
ALTER ROLE obsidian_readonly SET lock_timeout = '3s';
ALTER ROLE obsidian_readonly SET idle_in_transaction_session_timeout = '30s';
ALTER ROLE obsidian_payout SET statement_timeout = '30s';
ALTER ROLE obsidian_payout SET lock_timeout = '5s';
ALTER ROLE obsidian_payout SET idle_in_transaction_session_timeout = '30s';
