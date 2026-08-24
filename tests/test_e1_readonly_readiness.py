import importlib.util
import json
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PATH = ROOT / "deploy/check_e1_readonly_readiness.py"
SPEC = importlib.util.spec_from_file_location("e1_readiness", PATH)
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


def test_repository_contracts_are_ready():
    errors = []
    fixtures = gate._validate_fixtures(ROOT / "contracts/e1-readonly", errors)
    gate._validate_sources(ROOT, ROOT / "kairos", fixtures, errors)
    assert errors == []


def test_production_gate_rejects_any_connector_or_credential(tmp_path):
    state = tmp_path / "connectors.json"
    state.write_text(json.dumps({
        "version": 1,
        "items": {"src_x": {"credentialRef": "vault://forbidden"}},
        "idempotency": {}, "events": [],
    }), encoding="utf-8")
    errors = []
    gate._validate_keyless_state(state, errors)
    assert "production connector store is not keyless/empty" in errors
    assert "production connector store contains credential material" in errors


def test_absent_state_is_valid_and_not_created(tmp_path):
    state = tmp_path / "missing.json"
    errors = []
    gate._validate_keyless_state(state, errors)
    assert errors == [] and not state.exists()


def test_fixture_field_drift_is_no_go(tmp_path):
    contract_dir = tmp_path / "contracts"
    shutil.copytree(ROOT / "contracts/e1-readonly", contract_dir)
    path = contract_dir / "connector-events.v1.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["events"][0]["ownerRef"] = "forbidden"
    path.write_text(json.dumps(data), encoding="utf-8")
    errors = []
    gate._validate_fixtures(contract_dir, errors)
    assert any("connector event: exact fields differ" in error for error in errors)
