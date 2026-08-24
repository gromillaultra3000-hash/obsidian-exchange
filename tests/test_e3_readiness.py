import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_readiness import (CHECKS, CURRENT_PROBES, assess_e3_readiness,
                              validate_e3_readiness)


def test_current_proof_is_exact_code_complete_operational_no_go():
    proof = assess_e3_readiness(CURRENT_PROBES)
    assert proof["status"] == "NO_GO"
    assert proof["stage"] == "OFFLINE_FOUNDATION_COMPLETE"
    assert proof["blockers"] == list(CHECKS[6:])
    assert proof["eligibleForRuntimePreparation"] is False
    assert proof["runtimeEnableAllowed"] is False
    assert proof["actionAllowed"] is False
    assert proof["schemaVersion"] == "e3-readiness-proof.v2"
    assert "INDEPENDENT_VERIFIER_BINDING_ACCEPTED" in proof["blockers"]
    assert validate_e3_readiness(json.loads(json.dumps(proof))) == proof


def test_every_operational_prerequisite_is_independently_required():
    for check_id in CHECKS[6:]:
        probes = {name: True for name in CHECKS}
        probes[check_id] = False
        proof = assess_e3_readiness(probes)
        assert proof["status"] == "NO_GO"
        assert proof["blockers"] == [check_id]
        assert proof["runtimeEnableAllowed"] is False


def test_synthetic_all_true_go_still_cannot_enable_or_execute():
    proof = assess_e3_readiness({name: True for name in CHECKS})
    assert proof["status"] == "GO"
    assert proof["ready"] is True
    assert proof["eligibleForRuntimePreparation"] is True
    assert proof["runtimeEnableAllowed"] is False
    assert proof["executionEffect"] == "NONE"
    assert proof["actionAllowed"] is False


@pytest.mark.parametrize("mutation", [
    lambda value: value.update(status="GO"),
    lambda value: value.update(blockers=[]),
    lambda value: value.update(runtimeEnableAllowed=True),
    lambda value: value["checks"][6].update(ready=True),
    lambda value: value.update(proofId="e3p_" + "0" * 64),
])
def test_proof_tamper_fails_closed(mutation):
    changed = copy.deepcopy(assess_e3_readiness(CURRENT_PROBES))
    mutation(changed)
    with pytest.raises(ValueError):
        validate_e3_readiness(changed)


@pytest.mark.parametrize("bad", [
    {}, {**CURRENT_PROBES, "EXTRA": False},
    {**CURRENT_PROBES, "ENGINE_ADAPTER_READY": 1},
])
def test_probe_schema_is_exact_boolean_and_fail_closed(bad):
    with pytest.raises(ValueError):
        assess_e3_readiness(bad)


def test_cli_is_stdout_only_deterministic_no_go():
    command = [sys.executable, str(ROOT / "kairos/scripts/check_e3_offline_readiness.py")]
    first = subprocess.run(command, text=True, capture_output=True, check=False)
    second = subprocess.run(command, text=True, capture_output=True, check=False)
    assert first.returncode == second.returncode == 1
    assert first.stderr == second.stderr == ""
    assert first.stdout == second.stdout
    assert json.loads(first.stdout)["status"] == "NO_GO"
