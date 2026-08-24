import os
import sys
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.reporting_store import PostgresReportingStore

dsn = os.environ["TEST_POSTGRES_DSN"]
import psycopg

with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute("DROP TABLE IF EXISTS payment_sessions,provider_health,orders,reserves,limit_orders,dca_schedules CASCADE")
    cur.execute("CREATE TABLE orders(order_id bigint PRIMARY KEY,user_id bigint,username text,currency text,status text,rub_amount numeric,paid_btc_tx text,created_at timestamptz)")
    cur.execute("CREATE TABLE payment_sessions(id bigint PRIMARY KEY,order_id bigint,provider text,created_at timestamptz)")
    cur.execute("CREATE TABLE provider_health(provider text PRIMARY KEY,is_healthy boolean,failed_count integer,avg_response_time numeric,status text,blocker text)")
    cur.execute("CREATE TABLE reserves(currency text PRIMARY KEY,amount numeric,updated_at timestamptz)")
    cur.execute("CREATE TABLE limit_orders(id bigint PRIMARY KEY,status text)")
    cur.execute("CREATE TABLE dca_schedules(id bigint PRIMARY KEY,status text)")
    cur.execute("INSERT INTO orders VALUES(1,10,'u10','BTC','sent',1000,'tx1',now()),(2,20,'u20','LTC','paid',2000,NULL,now()),(3,30,'u30','USDT','pending',3000,NULL,now())")
    cur.execute("INSERT INTO payment_sessions VALUES(1,1,'P',now()),(2,2,'P',now()),(3,3,'P',now())")
    cur.execute("INSERT INTO provider_health VALUES('P',true,0,0.5,'READY','')")
    cur.execute("INSERT INTO reserves VALUES('BTC',2,now()),('RUB',0,now())")

store = PostgresReportingStore(dsn)
assert store.provider_conversion_rows(30) == [{"provider": "P", "shown": 3, "paid": 2}]
assert len(store.completed_evidence_rows(30)) == 2
assert store.public_stats() == {"exchanges_today": 1, "exchanges_total": 1,
                                "volume_24h": Decimal("1000"), "volume_total": Decimal("1000")}
assert store.reserves(positive_only=True) == [("BTC", Decimal("2"))]
assert [r[:2] for r in store.reserves_detailed()] == [("BTC", Decimal("2")), ("RUB", Decimal("0"))]
assert store.bot_today_summary() == {"today_count": 3, "today_volume": Decimal("6000"),
    "today_sent": 1, "today_sent_volume": Decimal("1000"), "pending": 1, "paid": 1,
    "new_users": 3, "active_limits": 0, "active_dca": 0}
assert store.admin_stats() == {"total": 3, "pending": 1, "sent": 1, "volume": Decimal("1000")}
assert store.site_stats() == {"total": 3, "completed": 2, "attempted": 2}
assert store.today_status_counts() == {
    "total": 3, "pending": 1, "completed": 2, "expired": 0}
assert store.stuck_pending_orders(older_than_minutes=0)["count"] == 1
assert store.recent_conversion() == {"total": 3, "paid": 2}
assert store.daily_order_stats() == {"total": 3, "paid": 2,
                                     "volume": Decimal("3000"), "users": 3}
today = __import__("datetime").date.today().isoformat()
assert store.period_order_report(today, today) == {
    "sent_count": 1, "sent_volume": Decimal("1000"), "total_count": 3,
    "currencies": [("BTC", 1, Decimal("1000"))], "new_users": 3}
cumulative = store.cumulative_stats({"Сегодня": today}, today,
                                    ["BTC", "LTC", "USDT"],
                                    ["pending", "paid", "sent"])
assert cumulative["periods"]["Сегодня"] == (1, Decimal("1000"))
assert cumulative["currencies"]["BTC"] == (1, Decimal("1000"))
assert cumulative["statuses"] == {"pending": 1, "paid": 1, "sent": 1}
analytics = store.admin_analytics()
assert analytics["totals"] == {"total_orders": 3, "total_volume": Decimal("6000"),
    "paid_orders": 2, "paid_volume": Decimal("3000")}
assert analytics["recent"][0]["provider"] == "P"
assert analytics["providers"][0]["status"] == "READY"

print("PostgreSQL reporting repository checks: OK")
