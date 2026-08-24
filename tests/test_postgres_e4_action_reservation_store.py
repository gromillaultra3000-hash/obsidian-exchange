import os
import sys
import copy
import threading
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

dsn = os.getenv("TEST_POSTGRES_DSN")
if not dsn:
    print("postgres E4 action reservation store: skipped (TEST_POSTGRES_DSN unset)")
    raise SystemExit(0)

import psycopg
from core.e4_action_reservation import build_action_reservation_request
from repositories.e4_action_reservation_store import PostgresE4ActionReservationStore
from test_e4_private_action_adapter import assessment

with psycopg.connect(dsn) as conn:
    conn.execute("DROP TABLE IF EXISTS e4_action_reservations")
    conn.execute((ROOT / "tests/e4_action_reservation_rehearsal.sql").read_text())

args, result = assessment()
request = build_action_reservation_request(
    draft=args["draft"], assessment=result,
    requested_at_epoch_ms=result["assessedAtEpochMs"] + 1,
    expires_at_epoch_ms=min(result["assessedAtEpochMs"] + 10_001,
                            args["draft"]["quoteExpiresAtEpochMs"]))
store = PostgresE4ActionReservationStore(dsn)
barrier = threading.Barrier(2)
results = []
def reserve_once():
    barrier.wait()
    results.append(PostgresE4ActionReservationStore(dsn).reserve(request))
threads = [threading.Thread(target=reserve_once) for _ in range(2)]
for thread in threads: thread.start()
for thread in threads: thread.join()
assert sorted(item["action"] for item in results) == ["replayed", "reserved"]
assert store.reserve(request)["action"] == "replayed"
changed = copy.deepcopy(request)
changed["expiresAtEpochMs"] += 1
from core.e4_action_reservation import _hash
unsigned = dict(changed); unsigned.pop("requestId")
changed["requestId"] = "parr_" + _hash(unsigned)
assert store.reserve(changed)["action"] == "conflict"
with psycopg.connect(dsn) as conn:
    assert conn.execute("SELECT count(*) FROM e4_action_reservations").fetchone()[0] == 1
    conn.execute("DROP TABLE e4_action_reservations")
print("PostgreSQL E4 action reservation repository checks: OK")
