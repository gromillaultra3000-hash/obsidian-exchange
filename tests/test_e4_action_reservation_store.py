import copy
import sqlite3
import sys
import tempfile
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_action_reservation import build_action_reservation_request
from repositories.e4_action_reservation_store import SQLiteE4ActionReservationStore
from test_e4_private_action_adapter import assessment


def schema(path):
    with sqlite3.connect(path) as conn:
        conn.execute("""CREATE TABLE e4_action_reservations(
          reservation_id TEXT PRIMARY KEY,request_id TEXT NOT NULL UNIQUE,
          draft_id TEXT NOT NULL UNIQUE,assessment_id TEXT NOT NULL,
          principal_ref TEXT NOT NULL,actor_user_id INTEGER NOT NULL,
          idempotency_key_sha256 TEXT NOT NULL,
          workflow_mapping TEXT NOT NULL,payload_sha256 TEXT NOT NULL,
          quote_expires_at_epoch_ms INTEGER NOT NULL,
          requested_at_epoch_ms INTEGER NOT NULL,expires_at_epoch_ms INTEGER NOT NULL,
          state TEXT NOT NULL CHECK(state IN('reserved','committed')),
          result_kind TEXT,result_id INTEGER,created_at TEXT DEFAULT CURRENT_TIMESTAMP,
          UNIQUE(principal_ref,idempotency_key_sha256))""")


def request(side="BUY_CRYPTO"):
    args, result = assessment(side)
    requested_at = result["assessedAtEpochMs"] + 1
    value = build_action_reservation_request(
        draft=args["draft"], assessment=result,
        requested_at_epoch_ms=requested_at,
        expires_at_epoch_ms=min(
            requested_at + 10_000, args["draft"]["quoteExpiresAtEpochMs"]))
    return value


def test_exact_retry_is_same_reservation_and_drift_conflicts():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "store.db")
        schema(path)
        store = SQLiteE4ActionReservationStore(path)
        value = request()
        assert store.reserve(value) == {"action": "reserved", "reservation_id": value["requestId"]}
        assert store.reserve(copy.deepcopy(value)) == {
            "action": "replayed", "reservation_id": value["requestId"]}
        changed = copy.deepcopy(value)
        changed["assessmentId"] = "pasa_" + "0" * 64
        unsigned = dict(changed); unsigned.pop("requestId")
        from core.e4_action_reservation import _hash
        changed["requestId"] = "parr_" + _hash(unsigned)
        assert store.reserve(changed)["action"] == "conflict"


def test_parallel_reservation_has_one_winner_and_one_exact_replay():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "store.db")
        schema(path)
        value = request()
        barrier, results = threading.Barrier(2), []
        def worker():
            barrier.wait()
            results.append(SQLiteE4ActionReservationStore(path).reserve(value))
        threads = [threading.Thread(target=worker) for _ in range(2)]
        for thread in threads: thread.start()
        for thread in threads: thread.join()
        assert sorted(item["action"] for item in results) == ["replayed", "reserved"]
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM e4_action_reservations").fetchone()[0] == 1


def test_fault_after_insert_rolls_back_and_retry_can_reserve():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "store.db")
        schema(path)
        value = request()
        def fail(): raise RuntimeError("injected")
        with pytest.raises(RuntimeError):
            SQLiteE4ActionReservationStore(path, fault_after_insert=fail).reserve(value)
        with sqlite3.connect(path) as conn:
            assert conn.execute("SELECT COUNT(*) FROM e4_action_reservations").fetchone()[0] == 0
        assert SQLiteE4ActionReservationStore(path).reserve(value)["action"] == "reserved"


def test_expiry_never_releases_idempotency_for_drift():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "store.db")
        schema(path)
        store, value = SQLiteE4ActionReservationStore(path), request()
        store.reserve(value)
        changed = copy.deepcopy(value)
        changed["expiresAtEpochMs"] += 1
        from core.e4_action_reservation import _hash
        unsigned = dict(changed); unsigned.pop("requestId")
        changed["requestId"] = "parr_" + _hash(unsigned)
        assert store.reserve(changed)["action"] == "conflict"


def test_store_contains_no_generic_sql_or_money_workflow_invocation():
    source = (ROOT / "relay/repositories/e4_action_reservation_store.py").read_text()
    assert "def execute(" not in source
    for forbidden in ("create_order", "create_sell", "payment", "payout", "send_crypto"):
        assert forbidden not in source
