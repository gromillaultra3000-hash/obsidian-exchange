import os
from pathlib import Path

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 relay-shadow denial rehearsal: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
PROPOSAL = (ROOT / "deploy/postgres/proposals/027_e0_relay_shadow_no_db.sql").read_text()


def denied(statement):
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute("SET ROLE obsidian_relay_shadow")
            conn.execute(statement)
    except psycopg.Error:
        return
    raise AssertionError(f"statement unexpectedly allowed: {statement}")


with psycopg.connect(dsn) as conn:
    conn.execute("CREATE TABLE orders(order_id bigserial primary key,status text not null)")
    conn.execute("CREATE TABLE payout_intents(id bigserial primary key,state text not null)")
    conn.execute("CREATE FUNCTION claim_next_order_payout() RETURNS bigint LANGUAGE sql AS 'SELECT 1::bigint'")
    conn.execute("""DO $$ BEGIN EXECUTE format(
      'REVOKE CONNECT,TEMPORARY ON DATABASE %I FROM PUBLIC',current_database()); END $$""")
    conn.execute("REVOKE ALL ON SCHEMA public FROM PUBLIC")
    conn.execute("REVOKE ALL ON ALL TABLES IN SCHEMA public FROM PUBLIC")
    conn.execute("REVOKE ALL ON ALL SEQUENCES IN SCHEMA public FROM PUBLIC")
    conn.execute("REVOKE ALL ON ALL FUNCTIONS IN SCHEMA public FROM PUBLIC")
    conn.execute(PROPOSAL)

with psycopg.connect(dsn) as conn:
    role = conn.execute("""SELECT rolcanlogin,rolsuper,rolcreatedb,rolcreaterole,
      rolinherit,rolreplication,rolbypassrls
      FROM pg_roles WHERE rolname='obsidian_relay_shadow'""").fetchone()
    assert role == (False,False,False,False,False,False,False)
    assert conn.execute("""SELECT rolpassword IS NULL FROM pg_authid
      WHERE rolname='obsidian_relay_shadow'""").fetchone()[0] is True
    assert conn.execute("""SELECT count(*) FROM pg_auth_members
      WHERE roleid=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_shadow')
         OR member=(SELECT oid FROM pg_roles WHERE rolname='obsidian_relay_shadow')""").fetchone()[0] == 0
    assert conn.execute("""SELECT
      has_database_privilege('obsidian_relay_shadow',current_database(),'CONNECT'),
      has_database_privilege('obsidian_relay_shadow',current_database(),'TEMPORARY'),
      has_schema_privilege('obsidian_relay_shadow','public','USAGE'),
      has_table_privilege('obsidian_relay_shadow','orders','SELECT'),
      has_sequence_privilege('obsidian_relay_shadow','orders_order_id_seq','USAGE'),
      has_function_privilege('obsidian_relay_shadow','claim_next_order_payout()','EXECUTE')
    """).fetchone() == (False,False,False,False,False,False)


def proposal_rejected_after(statement, expected_marker):
    try:
        with psycopg.connect(dsn) as conn:
            conn.execute(statement)
            conn.execute(PROPOSAL)
    except psycopg.Error as exc:
        assert expected_marker in str(exc)
        return
    raise AssertionError(f"proposal accepted ambient privilege: {expected_marker}")


proposal_rejected_after(
    """DO $$ BEGIN EXECUTE format(
      'GRANT CONNECT ON DATABASE %I TO PUBLIC',current_database()); END $$""",
    "relay_shadow_ambient_database_privilege",
)
proposal_rejected_after(
    "CREATE FUNCTION ambient_money_function() RETURNS bigint LANGUAGE sql AS 'SELECT 1::bigint'",
    "relay_shadow_ambient_function_execute",
)

shadow_dsn = conninfo_to_dict(dsn)
shadow_dsn.update(user="obsidian_relay_shadow",password="synthetic-not-a-secret",connect_timeout="2")
try:
    psycopg.connect(make_conninfo(**shadow_dsn))
except psycopg.Error:
    pass
else:
    raise AssertionError("NOLOGIN relay-shadow unexpectedly connected")

for statement in (
    "SELECT * FROM orders",
    "INSERT INTO payout_intents(state) VALUES('ready')",
    "SELECT nextval('orders_order_id_seq')",
    "SELECT claim_next_order_payout()",
    "CREATE TABLE forbidden(id bigint)",
    "CREATE TEMP TABLE forbidden_temp(id bigint)",
    "ALTER ROLE obsidian_relay_shadow LOGIN",
):
    denied(statement)

print("E0.3 relay-shadow NOLOGIN, connection and money-SQL denial rehearsal: OK")
