import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_paper_admission import create_admission_control
from app.e3_engine_attempts import invoke_paper_engine_once
from app.e3_engine_evidence import build_paper_engine_evidence_bundle
from app.e3_persistence import GENESIS_HASH, PostgresE3EvidenceStore
from test_e3_engine_adapter import FakeEngine, NOW, ready_intent


class Result:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class Connection:
    def __init__(self, calls, row): self.calls, self.row = calls, row
    def __enter__(self): return self
    def __exit__(self, *args): return False
    def execute(self, sql, params):
        self.calls.append((sql, params)); return Result(self.row)


def factory(calls, row={"appended": True}):
    return lambda: Connection(calls, row)


def test_repository_validates_and_calls_one_atomic_server_function():
    calls = []
    control = create_admission_control(account_id="sandbox_1")
    store = PostgresE3EvidenceStore(factory(calls))
    assert store.append("ADMISSION_CONTROL", control) is True
    assert len(calls) == 1
    sql, params = calls[0]
    assert "e3_append_paper_evidence" in sql
    assert params[:6] == ("ADMISSION_CONTROL", control["controlId"], "sandbox_1",
                          0, control["controlHash"], GENESIS_HASH)
    assert json.loads(params[6]) == control


def test_repository_exact_retry_result_and_head_are_decoded():
    calls = []
    control = create_admission_control(account_id="sandbox_1")
    assert PostgresE3EvidenceStore(factory(calls, {"appended": False})).append(
        "ADMISSION_CONTROL", control) is False
    head_calls = []
    head = PostgresE3EvidenceStore(factory(
        head_calls, {"sequence": 0, "document_id": control["controlId"],
                     "document_hash": control["controlHash"]})).head(
                         "ADMISSION_CONTROL", "sandbox_1")
    assert head["document_hash"] == control["controlHash"]


def test_invalid_kind_or_tampered_contract_never_reaches_database():
    calls = []
    store = PostgresE3EvidenceStore(factory(calls))
    with pytest.raises(ValueError): store.append("OTHER", {})
    changed = create_admission_control(account_id="sandbox_1")
    changed["actionAllowed"] = True
    with pytest.raises(ValueError): store.append("ADMISSION_CONTROL", changed)
    assert calls == []


def test_engine_bundle_is_validated_then_appended_atomically():
    ready = ready_intent()
    submission, attempt, receipt = invoke_paper_engine_once(
        ready, FakeEngine(), started_at_epoch_ms=NOW + 1,
        finished_at_epoch_ms=NOW + 3)
    bundle = build_paper_engine_evidence_bundle(
        sequence=0, previous_bundle_hash=GENESIS_HASH,
        ready_intent=ready, submission=submission, attempt=attempt,
        receipt=receipt)
    calls = []
    assert PostgresE3EvidenceStore(factory(calls)).append(
        "ENGINE_EVIDENCE", bundle) is True
    assert len(calls) == 1
    _, params = calls[0]
    assert params[:6] == (
        "ENGINE_EVIDENCE", bundle["bundleId"], "sandbox_1", 0,
        bundle["bundleHash"], GENESIS_HASH)
    assert json.loads(params[6]) == bundle
    with pytest.raises(ValueError, match="previous hash"):
        PostgresE3EvidenceStore(factory([])).append(
            "ENGINE_EVIDENCE", bundle, previous_document_hash="f" * 64)


def test_migration_is_append_only_bounded_atomic_and_not_in_cutover_chain():
    sql = (ROOT / "deploy/postgres/024_e3_paper_evidence.sql").read_text()
    assert "CHECK(octet_length(payload::text)<=1048576)" in sql
    assert "BEFORE UPDATE OR DELETE ON e3_paper_evidence" in sql
    assert "FOR UPDATE" in sql
    assert "continuity conflict" in sql and "idempotency drift" in sql
    assert "REVOKE UPDATE,DELETE,TRUNCATE" in sql
    assert "ENGINE_EVIDENCE" in sql
    loader = (ROOT / "deploy/postgres/load_production_snapshot.py").read_text()
    assert "024_e3_paper_evidence.sql" not in loader
