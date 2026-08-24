-- E0.3 PROPOSAL ONLY. Rehearse on a disposable PostgreSQL 17 database.
-- The shadow process must receive no database credential or connection path.
-- Production application requires separately authorized migration/rollback.
BEGIN;

DO $role$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname='obsidian_relay_shadow') THEN
    CREATE ROLE obsidian_relay_shadow NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
      NOINHERIT NOREPLICATION NOBYPASSRLS;
  END IF;
END
$role$;

ALTER ROLE obsidian_relay_shadow NOLOGIN PASSWORD NULL NOSUPERUSER NOCREATEDB
  NOCREATEROLE NOINHERIT NOREPLICATION NOBYPASSRLS;

DO $memberships$
DECLARE item record;
BEGIN
  FOR item IN
    SELECT parent.rolname AS parent_name
      FROM pg_auth_members AS membership
      JOIN pg_roles AS parent ON parent.oid=membership.roleid
     WHERE membership.member=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_shadow')
  LOOP
    EXECUTE format('REVOKE %I FROM obsidian_relay_shadow',item.parent_name);
  END LOOP;
  FOR item IN
    SELECT member.rolname AS member_name
      FROM pg_auth_members AS membership
      JOIN pg_roles AS member ON member.oid=membership.member
     WHERE membership.roleid=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_shadow')
  LOOP
    EXECUTE format('REVOKE obsidian_relay_shadow FROM %I',item.member_name);
  END LOOP;
END
$memberships$;

DO $database_acl$
BEGIN
  EXECUTE format('REVOKE ALL ON DATABASE %I FROM obsidian_relay_shadow',current_database());
END
$database_acl$;
REVOKE ALL ON SCHEMA public FROM obsidian_relay_shadow;
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM obsidian_relay_shadow;
REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM obsidian_relay_shadow;
REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM obsidian_relay_shadow;

DO $fail_closed$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_authid
     WHERE rolname='obsidian_relay_shadow'
       AND (rolcanlogin OR rolpassword IS NOT NULL)
  ) THEN
    RAISE EXCEPTION 'relay_shadow_login_or_password_present';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_auth_members
     WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_shadow')
        OR member=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_shadow')
  ) THEN
    RAISE EXCEPTION 'relay_shadow_role_membership_present';
  END IF;
  IF has_database_privilege('obsidian_relay_shadow',current_database(),'CONNECT')
     OR has_database_privilege('obsidian_relay_shadow',current_database(),'TEMPORARY') THEN
    RAISE EXCEPTION 'relay_shadow_ambient_database_privilege';
  END IF;
  IF has_schema_privilege('obsidian_relay_shadow','public','USAGE')
     OR has_schema_privilege('obsidian_relay_shadow','public','CREATE') THEN
    RAISE EXCEPTION 'relay_shadow_ambient_schema_privilege';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class AS relation
     JOIN pg_namespace AS namespace ON namespace.oid=relation.relnamespace
    WHERE namespace.nspname='public'
      AND relation.relkind IN ('r','p','v','m','f')
      AND (has_table_privilege('obsidian_relay_shadow',relation.oid,'SELECT')
        OR has_table_privilege('obsidian_relay_shadow',relation.oid,'INSERT')
        OR has_table_privilege('obsidian_relay_shadow',relation.oid,'UPDATE')
        OR has_table_privilege('obsidian_relay_shadow',relation.oid,'DELETE')
        OR has_table_privilege('obsidian_relay_shadow',relation.oid,'TRUNCATE')
        OR has_table_privilege('obsidian_relay_shadow',relation.oid,'REFERENCES')
        OR has_table_privilege('obsidian_relay_shadow',relation.oid,'TRIGGER'))
  ) THEN
    RAISE EXCEPTION 'relay_shadow_ambient_relation_privilege';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_class AS relation
     JOIN pg_namespace AS namespace ON namespace.oid=relation.relnamespace
    WHERE namespace.nspname='public' AND relation.relkind='S'
      AND (has_sequence_privilege('obsidian_relay_shadow',relation.oid,'USAGE')
        OR has_sequence_privilege('obsidian_relay_shadow',relation.oid,'SELECT')
        OR has_sequence_privilege('obsidian_relay_shadow',relation.oid,'UPDATE'))
  ) THEN
    RAISE EXCEPTION 'relay_shadow_ambient_sequence_privilege';
  END IF;
  IF EXISTS (
    SELECT 1 FROM pg_proc AS procedure
     JOIN pg_namespace AS namespace ON namespace.oid=procedure.pronamespace
    WHERE namespace.nspname='public'
      AND has_function_privilege('obsidian_relay_shadow',procedure.oid,'EXECUTE')
  ) THEN
    RAISE EXCEPTION 'relay_shadow_ambient_function_execute';
  END IF;
END
$fail_closed$;

COMMIT;
