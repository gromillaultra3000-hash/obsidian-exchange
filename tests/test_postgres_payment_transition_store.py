import os,sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"relay"))
dsn=os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres payment transition store: skipped (TEST_POSTGRES_DSN unset)"); raise SystemExit(0)
from repositories.payment_transition_store import PostgresPaymentTransitionStore
store=PostgresPaymentTransitionStore(dsn)
assert store.mark_paid(1,provider="vertu",evidence="poll",session_token="live")["action"]=="transitioned"
assert store.mark_paid(1,provider="vertu",evidence="retry")["action"]=="already_paid"
assert store.mark_paid(2,provider="lava",evidence="callback")["action"]=="status_conflict"
item=store.claim_notification(); assert item and store.retry_notification(item["id"])
item=store.claim_notification(); assert item["attempts"]==2 and store.mark_notification_sent(item["id"])
assert store.claim_notification() is None
print("PostgreSQL payment transition repository checks: OK")
