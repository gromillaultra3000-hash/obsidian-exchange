import json
import multiprocessing
import os
import stat
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "lumi") not in sys.path:
    sys.path.insert(0, str(ROOT / "lumi"))

from lumi.app.integration.shadow_replay_store import AtomicReplayStore

NOW = 1786424405
KEY_ID = "kairos-shadow-test-v1"
NONCE = "AQIDBAUGBwgJCgsMDQ4PEBES"


def store(path, **changes):
    now = changes.pop("now", NOW)
    return AtomicReplayStore(path, capacity=changes.pop("capacity", 16),
                             clock=lambda: now, **changes)


def _consume_worker(path, index, queue):
    try:
        nonce = f"AAAAAAAAAAAAAAAAAAAAAA{index:02d}"
        AtomicReplayStore(
            Path(path), capacity=16, clock=lambda: NOW).consume(
                KEY_ID, nonce, NOW + 30)
        queue.put("OK")
    except Exception as exc:
        queue.put(type(exc).__name__)


def _same_nonce_worker(path, queue):
    try:
        AtomicReplayStore(
            Path(path), capacity=16, clock=lambda: NOW).consume(
                KEY_ID, NONCE, NOW + 30)
        queue.put("OK")
    except Exception as exc:
        queue.put(str(exc))


def test_restart_replay_rejection_and_narrow_permissions(tmp_path):
    path = tmp_path / "ledger.json"
    first = store(path)
    first.consume(KEY_ID, NONCE, NOW + 30)
    restarted = store(path)
    with pytest.raises(ValueError, match="replayed"):
        restarted.consume(KEY_ID, NONCE, NOW + 30)
    assert restarted.snapshot()["entryCount"] == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert stat.S_IMODE(path.with_suffix(".json.lock").stat().st_mode) == 0o600


def test_multiprocess_unique_consumes_are_serialized_without_lost_updates(tmp_path):
    path = tmp_path / "ledger.json"
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    workers = [context.Process(target=_consume_worker, args=(path, index, queue))
               for index in range(8)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    assert [queue.get(timeout=2) for _ in workers] == ["OK"] * len(workers)
    assert store(path).snapshot()["entryCount"] == len(workers)


def test_multiprocess_same_nonce_is_accepted_exactly_once(tmp_path):
    path = tmp_path / "ledger.json"
    context = multiprocessing.get_context("fork")
    queue = context.Queue()
    workers = [context.Process(target=_same_nonce_worker, args=(path, queue))
               for _ in range(6)]
    for worker in workers:
        worker.start()
    for worker in workers:
        worker.join(10)
        assert worker.exitcode == 0
    outcomes = [queue.get(timeout=2) for _ in workers]
    assert outcomes.count("OK") == 1
    assert outcomes.count("shadow service request replayed") == len(workers) - 1
    assert store(path).snapshot()["entryCount"] == 1


def test_fault_before_replace_preserves_previous_snapshot_and_cleans_temp(tmp_path):
    path = tmp_path / "ledger.json"
    store(path).consume(KEY_ID, NONCE, NOW + 30)
    before = path.read_bytes()

    def fail(stage):
        if stage == "after_temp_fsync":
            raise RuntimeError("injected crash")

    with pytest.raises(RuntimeError, match="injected"):
        store(path, fault=fail).consume(
            KEY_ID, "AgMEBQYHCAkKCwwNDg8QERIT", NOW + 30)
    assert path.read_bytes() == before
    assert store(path).snapshot()["entryCount"] == 1
    assert not list(tmp_path.glob(".ledger.json.tmp.*"))


def test_fault_after_replace_leaves_valid_committed_snapshot_and_retry_rejects(tmp_path):
    path = tmp_path / "ledger.json"

    def fail(stage):
        if stage == "after_replace":
            raise RuntimeError("uncertain commit")

    with pytest.raises(RuntimeError, match="uncertain"):
        store(path, fault=fail).consume(KEY_ID, NONCE, NOW + 30)
    assert store(path).snapshot()["entryCount"] == 1
    with pytest.raises(ValueError, match="replayed"):
        store(path).consume(KEY_ID, NONCE, NOW + 30)


@pytest.mark.parametrize("raw", [b"{", b"[]", b'{"schemaVersion":"wrong"}'])
def test_corrupt_or_partial_state_fails_closed(tmp_path, raw):
    path = tmp_path / "ledger.json"
    path.write_bytes(raw)
    path.chmod(0o600)
    with pytest.raises(ValueError):
        store(path).snapshot()


def test_oversized_permissive_and_symlink_state_fail_closed(tmp_path):
    oversized = tmp_path / "oversized.json"
    oversized.write_bytes(b"x" * (1024 * 1024 + 1))
    oversized.chmod(0o600)
    with pytest.raises(ValueError, match="invalid"):
        store(oversized).snapshot()

    permissive = tmp_path / "permissive.json"
    permissive.write_text(json.dumps(store(tmp_path / "absent").snapshot()))
    permissive.chmod(0o644)
    with pytest.raises(ValueError, match="invalid"):
        store(permissive).snapshot()

    target = tmp_path / "target.json"
    target.write_text("{}")
    link = tmp_path / "link.json"
    link.symlink_to(target)
    with pytest.raises(ValueError):
        store(link).snapshot()


def test_capacity_and_expiry_are_preserved_by_file_adapter(tmp_path):
    path = tmp_path / "ledger.json"
    first = AtomicReplayStore(path, capacity=1, clock=lambda: NOW)
    first.consume(KEY_ID, NONCE, NOW + 30)
    with pytest.raises(ValueError, match="capacity"):
        first.consume(KEY_ID, "AgMEBQYHCAkKCwwNDg8QERIT", NOW + 30)
    later = AtomicReplayStore(path, capacity=1, clock=lambda: NOW + 31)
    result = later.consume(KEY_ID, "AgMEBQYHCAkKCwwNDg8QERIT", NOW + 61)
    assert result["prunedCount"] == 1


def test_constructor_and_import_create_no_state(tmp_path):
    path = tmp_path / "ledger.json"
    AtomicReplayStore(path, capacity=2, clock=lambda: NOW)
    assert list(tmp_path.iterdir()) == []
