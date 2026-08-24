import os
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[1]
dsn = os.environ["TEST_POSTGRES_DSN"]
schema = (ROOT / "deploy/postgres/020_legacy_runtime.sql").read_text()
tables = {
    "admin_log", "client_address_notes", "payout_queue", "payout_shadow",
    "rate_subscriptions", "referral_bonuses", "reviews", "risk_events",
    "user_vip_volume", "worker_ids",
}

with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    for table in tables:
        cur.execute(f'DROP TABLE IF EXISTS "{table}" CASCADE')
    cur.execute(schema)
    cur.execute("SELECT table_name FROM information_schema.tables "
                "WHERE table_schema='public' AND table_name=ANY(%s)", (list(tables),))
    assert {row[0] for row in cur.fetchall()} == tables
    cur.execute("INSERT INTO reviews(order_id,user_id,rating,status) VALUES(1,2,5,'published')")
    cur.execute("INSERT INTO rate_subscriptions(user_id,enabled) VALUES(2,true)")
    cur.execute("INSERT INTO client_address_notes(user_id,currency,network,address,label,hidden,updated_at) "
                "VALUES(2,'BTC','BTC','bc1qtest','main',false,now())")
    cur.execute("INSERT INTO payout_shadow(order_id,would_auto_pay,rub_amount) VALUES(1,true,1000)")
    cur.execute("SELECT rating FROM reviews WHERE order_id=1")
    assert cur.fetchone()[0] == 5

print("PostgreSQL legacy-runtime schema checks: OK")
