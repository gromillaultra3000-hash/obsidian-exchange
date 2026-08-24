import os
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path
dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("E0.3 bot B4.2 rate-lock replacement: skipped")
    raise SystemExit(0)
import psycopg
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[1]
with psycopg.connect(dsn) as c:
    c.execute("CREATE TABLE blocked_users(user_id bigint PRIMARY KEY,reason text NOT NULL,blocked_at timestamptz NOT NULL DEFAULT now())")
    c.execute("CREATE TABLE orders(id bigserial PRIMARY KEY,order_id bigint UNIQUE,user_id bigint NOT NULL,created_at timestamptz NOT NULL DEFAULT now(),currency text NOT NULL DEFAULT 'BTC',rub_amount numeric NOT NULL DEFAULT 1,status text NOT NULL,crypto_address text,paid_btc_tx text,receipt_sent_at timestamptz,updated_at timestamptz,network text)")
    c.execute("CREATE TABLE sent_notifications(order_id bigint NOT NULL,event text NOT NULL,PRIMARY KEY(order_id,event))")
    c.execute("CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric NOT NULL,updated_at timestamptz NOT NULL DEFAULT now())")
    c.execute((ROOT / "deploy/postgres/004_rate_locks.sql").read_text())
    c.execute("INSERT INTO rate_locks(user_id,currency,locked_rate,fee_rub,locked_until) VALUES(7,'BTC',10,1,now()+interval '10 minutes'),(8,'LTC',20,1,now()+interval '10 minutes')")
    c.execute("CREATE FUNCTION fail_lock_insert() RETURNS trigger LANGUAGE plpgsql AS $$BEGIN IF NEW.user_id=8 AND NEW.locked_rate=999 THEN RAISE EXCEPTION 'injected'; END IF; RETURN NEW; END$$; CREATE TRIGGER fail_lock_insert BEFORE INSERT ON rate_locks FOR EACH ROW EXECUTE FUNCTION fail_lock_insert()")
    c.execute((ROOT / "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql").read_text())
    c.execute((ROOT / "deploy/postgres/proposals/046_e0_bot_b4_2_rate_lock_replacement.sql").read_text())
parts = conninfo_to_dict(dsn)
parts.update(user="obsidian_exchange_bot", password="synthetic-rehearsal-only")
bot = make_conninfo(**parts)

def replace(i):
    with psycopg.connect(bot) as c:
        return c.execute("SELECT bot_b4_replace_rate_lock(7,' btc ',%s,10,now()+interval '15 minutes')", (100 + i,)).fetchone()[0]

with ThreadPoolExecutor(max_workers=8) as pool: ids=list(pool.map(replace,range(8)))
assert len(set(ids))==8
invalid = (
    "SELECT bot_b4_replace_rate_lock(NULL,'BTC',1,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,NULL,1,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'',1,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'ETH',1,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',0,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC','NaN'::numeric,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC','Infinity'::numeric,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',1000000000000000000,0,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',1,NULL,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',1,-1,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',1,'Infinity'::numeric,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',1,1000000000000000000,now()+interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',1,0,now()-interval '1 minute')",
    "SELECT bot_b4_replace_rate_lock(1,'BTC',1,0,now()+interval '2 days')",
    "SELECT bot_b4_replace_rate_lock(8,'LTC',999,1,now()+interval '10 minutes')",
    "UPDATE rate_locks SET used=true",
    "INSERT INTO rate_locks(user_id,currency,locked_rate,fee_rub,locked_until) VALUES(1,'BTC',1,0,now())",
    "SELECT * FROM rate_locks",
    "SELECT nextval('rate_locks_id_seq')",
)
for sql in invalid:
    try:
        with psycopg.connect(bot) as c:
            c.execute(sql)
    except psycopg.Error:
        continue
    raise AssertionError("unexpectedly allowed: " + sql)
with psycopg.connect(dsn) as c:
    rows = c.execute("SELECT id,locked_rate,fee_rub,used,order_id,currency,locked_until FROM rate_locks WHERE id=ANY(%s) ORDER BY id", (ids,)).fetchall()
    assert len(rows) == 8 and {r[0] for r in rows} == set(ids)
    assert sum(not r[3] for r in rows) == 1
    assert all(r[2] == 10 and r[4] is None and r[5] == "BTC" and r[6] > datetime.now(timezone.utc) for r in rows)
    assert c.execute("SELECT count(*) FROM rate_locks WHERE user_id=7 AND currency='BTC' AND used=false").fetchone() == (1,)
    assert c.execute("SELECT count(*) FROM rate_locks WHERE user_id=7 AND currency='BTC' AND used=true").fetchone() == (8,)
    assert c.execute("SELECT used,locked_rate FROM rate_locks WHERE user_id=8 AND currency='LTC'").fetchone() == (False, 20)
    assert c.execute("SELECT count(*) FROM rate_locks WHERE user_id=8 AND locked_rate=999").fetchone() == (0,)
    assert c.execute("SELECT has_table_privilege('obsidian_exchange_bot','rate_locks','SELECT'),has_table_privilege('obsidian_exchange_bot','rate_locks','INSERT'),has_table_privilege('obsidian_exchange_bot','rate_locks','UPDATE'),has_sequence_privilege('obsidian_exchange_bot','rate_locks_id_seq','USAGE')").fetchone() == (False, False, False, False)
    fn = "public.bot_b4_replace_rate_lock(bigint,text,numeric,numeric,timestamp with time zone)"
    assert c.execute("SELECT has_function_privilege('public',to_regprocedure(%s),'EXECUTE'),has_function_privilege('obsidian_exchange_bot',to_regprocedure(%s),'EXECUTE')", (fn, fn)).fetchone() == (False, True)
    assert c.execute("SELECT p.prosecdef,p.provolatile,p.proconfig,r.rolcanlogin FROM pg_proc p JOIN pg_roles r ON r.oid=p.proowner WHERE p.oid=to_regprocedure(%s)", (fn,)).fetchone() == (True, "v", ["search_path=pg_catalog"], False)
print("E0.3 bot B4.2 rate-lock serialization, rollback and ambient denial: OK")
