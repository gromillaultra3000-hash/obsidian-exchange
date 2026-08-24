"""Disposable-PG17 behavioral rehearsal for canonical bounded 064A fingerprint."""
import os
import re
from pathlib import Path

import psycopg

DSN = os.environ.get("TEST_POSTGRES_DSN")
if not DSN:
    raise SystemExit("SKIP: TEST_POSTGRES_DSN is required")
SQL = Path(__file__).parents[1].joinpath(
    "deploy/postgres/b64_catalog_security_fingerprint.sql"
).read_text()
VERSION = "b64-catalog-security-fingerprint.v2"
SECTIONS = {
    "column_acl", "default_acl", "membership", "db_role_setting",
    "relation_security", "constraint_security", "index_security",
    "trigger_security", "function_security", "policy_security",
    "sequence_definition", "type_security", "extension_security",
}


def fp(conn):
    with conn.cursor() as cur:
        cur.execute(SQL)
        rows = None
        while True:
            if cur.description:
                rows = cur.fetchall()
            if not cur.nextset():
                break
        assert rows is not None
        assert len(rows) == len(SECTIONS)
        assert all(row[0] == VERSION for row in rows)
        result = {row[1]: (row[2], row[3]) for row in rows}
        assert set(result) == SECTIONS
        assert all(isinstance(count, int) and count >= 0 for count, _ in result.values())
        assert all(re.fullmatch(r"[0-9a-f]{64}", digest) for _, digest in result.values())
        return result


def mutate(conn, statement, expected_sections):
    if isinstance(expected_sections, str):
        expected_sections = {expected_sections}
    before = fp(conn)
    with conn.cursor() as cur:
        cur.execute(statement)
    conn.commit()
    after = fp(conn)
    changed = {section for section in SECTIONS if before[section] != after[section]}
    assert changed == set(expected_sections), (changed, expected_sections)
    return before, after


with psycopg.connect(DSN, autocommit=True) as conn:
    with conn.cursor() as cur:
        cur.execute("CREATE ROLE obsidian_b64_owner NOLOGIN")
        cur.execute("CREATE ROLE obsidian_b64_member NOLOGIN")
        cur.execute("CREATE TABLE public.b64_fixture (id bigint PRIMARY KEY, payload text)")
        cur.execute("CREATE TABLE public.b64_fixture_child (id bigint PRIMARY KEY, parent_id bigint REFERENCES public.b64_fixture(id))")
        cur.execute("CREATE SEQUENCE public.b64_fixture_seq")
        cur.execute("CREATE TYPE public.b64_fixture_state AS ENUM ('a', 'b')")
        cur.execute("CREATE FUNCTION public.b64_fixture_fn() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RETURN NEW; END $$")
        cur.execute("CREATE TRIGGER b64_fixture_trigger BEFORE INSERT ON public.b64_fixture FOR EACH ROW EXECUTE FUNCTION public.b64_fixture_fn()")

    baseline = fp(conn)
    assert baseline == fp(conn) == fp(conn)

    mutate(conn, "GRANT SELECT(payload) ON public.b64_fixture TO obsidian_b64_member", "column_acl")
    mutate(conn, "ALTER DEFAULT PRIVILEGES FOR ROLE obsidian_b64_owner IN SCHEMA public GRANT SELECT ON TABLES TO obsidian_b64_member", "default_acl")
    mutate(conn, "GRANT obsidian_b64_owner TO obsidian_b64_member WITH ADMIN OPTION", "membership")
    mutate(conn, "ALTER ROLE obsidian_b64_member IN DATABASE catalog_rehearsal SET statement_timeout='9s'", "db_role_setting")
    mutate(conn, "ALTER TABLE public.b64_fixture ENABLE ROW LEVEL SECURITY", "relation_security")
    mutate(conn, "CREATE POLICY b64_fixture_policy ON public.b64_fixture AS RESTRICTIVE FOR SELECT TO obsidian_b64_member USING (false)", "policy_security")
    mutate(conn, "ALTER TABLE public.b64_fixture DISABLE TRIGGER b64_fixture_trigger", "trigger_security")
    mutate(conn, "ALTER FUNCTION public.b64_fixture_fn() SECURITY DEFINER", "function_security")
    mutate(conn, "ALTER SEQUENCE public.b64_fixture_seq INCREMENT BY 7 CACHE 9 CYCLE", "sequence_definition")
    mutate(conn, "ALTER TYPE public.b64_fixture_state ADD VALUE 'c'", "type_security")
    mutate(conn, "GRANT USAGE ON TYPE public.b64_fixture_state TO PUBLIC", "type_security")
    mutate(conn, "ALTER SEQUENCE public.b64_fixture_seq OWNED BY public.b64_fixture.id", "sequence_definition")
    mutate(conn, "ALTER TABLE public.b64_fixture_child DISABLE TRIGGER ALL", "trigger_security")
    mutate(conn, "ALTER TABLE public.b64_fixture ADD CONSTRAINT b64_positive CHECK (id > 0) NOT VALID", "constraint_security")
    mutate(conn, "ALTER TABLE public.b64_fixture VALIDATE CONSTRAINT b64_positive", "constraint_security")
    mutate(conn, "CREATE INDEX b64_fixture_payload_idx ON public.b64_fixture(payload)", "index_security")
    mutate(conn, "CREATE DOMAIN public.b64_positive_id AS bigint CHECK (VALUE > 0)", {"type_security", "constraint_security"})

    before_state = fp(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT setval('public.b64_fixture_seq', 42, false)")
    assert fp(conn) == before_state

    with conn.cursor() as cur:
        cur.execute("CREATE SCHEMA b64_evil")
        cur.execute("SET search_path=b64_evil,public,pg_catalog")
    assert fp(conn) == before_state

    oid_churn_before = fp(conn)
    with conn.cursor() as cur:
        cur.execute("SELECT 'public.b64_fixture_fn()'::regprocedure::oid")
        old_oid = cur.fetchone()[0]
        cur.execute("DROP TRIGGER b64_fixture_trigger ON public.b64_fixture")
        cur.execute("DROP FUNCTION public.b64_fixture_fn()")
        cur.execute("CREATE FUNCTION public.b64_fixture_fn() RETURNS trigger LANGUAGE plpgsql SECURITY DEFINER AS $$ BEGIN RETURN NEW; END $$")
        cur.execute("CREATE TRIGGER b64_fixture_trigger BEFORE INSERT ON public.b64_fixture FOR EACH ROW EXECUTE FUNCTION public.b64_fixture_fn()")
        cur.execute("ALTER TABLE public.b64_fixture DISABLE TRIGGER b64_fixture_trigger")
        cur.execute("SELECT 'public.b64_fixture_fn()'::regprocedure::oid")
        new_oid = cur.fetchone()[0]
    assert new_oid != old_oid
    assert fp(conn) == oid_churn_before

print("PASS: canonical bounded catalog/security drift detected; sequence state excluded")
