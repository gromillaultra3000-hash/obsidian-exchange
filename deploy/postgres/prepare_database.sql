-- Bind one empty target database to the non-elevated migration owner.
-- Run as the cluster administrator while connected to that target, after
-- bootstrap_roles.sql and before migration 001.
DO $target$
BEGIN
    IF current_database() <> 'obsidian_exchange'
       AND current_database() NOT LIKE '%rehearsal%'
       AND current_database() NOT LIKE '%staging%'
       AND current_database() NOT LIKE '%contract%'
       AND current_database() NOT LIKE '%restore_smoke%' THEN
        RAISE EXCEPTION 'refusing unexpected database: %', current_database();
    END IF;

    EXECUTE format('ALTER DATABASE %I OWNER TO obsidian_migrator',
                   current_database());
    EXECUTE format('REVOKE CONNECT, TEMPORARY ON DATABASE %I FROM PUBLIC',
                   current_database());
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO obsidian_migrator, '
                   'obsidian_app, obsidian_readonly, obsidian_payout',
                   current_database());
END
$target$;

ALTER SCHEMA public OWNER TO obsidian_migrator;
REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE, CREATE ON SCHEMA public TO obsidian_migrator;
