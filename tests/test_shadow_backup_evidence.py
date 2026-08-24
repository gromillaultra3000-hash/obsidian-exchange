import copy
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT / "lumi") not in sys.path:
    sys.path.insert(0, str(ROOT / "lumi"))

from lumi.app.integration.shadow_backup_evidence import (
    assess_backup_evidence, validate_backup_evidence,
)

DIGEST = "a" * 64


def probes(**changes):
    value = {
        "schemaVersion": "shadow-backup-restore-probes.v1",
        "sourceDevice": 10,
        "primaryConfigured": True, "primaryDevice": 20,
        "secondaryConfigured": True, "secondaryDevice": 30,
        "primaryVerified": True, "secondaryVerified": True,
        "restoreRehearsed": True,
        "sourceHash": DIGEST, "primaryHash": DIGEST,
        "secondaryHash": DIGEST, "restoredHash": DIGEST,
    }
    value.update(changes)
    return value


def test_frozen_ready_evidence_requires_three_domains_and_matching_restore():
    expected = json.loads((
        ROOT / "contracts/e2-shadow/backup-restore-evidence-ready.v1.json"
    ).read_text())
    result = assess_backup_evidence(probes())
    assert result == expected
    assert validate_backup_evidence(result) == result
    assert result["independentBackup"] is True
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False


@pytest.mark.parametrize("changes", [
    {"primaryDevice": 10},
    {"secondaryDevice": 10},
    {"secondaryDevice": 20},
    {"restoredHash": "b" * 64},
    {"primaryHash": "b" * 64},
    {"secondaryHash": "b" * 64},
])
def test_shared_device_or_any_hash_mismatch_is_no_go(changes):
    result = assess_backup_evidence(probes(**changes))
    assert result["status"] == "NO_GO"
    assert result["independentBackup"] is False
    assert result["actionAllowed"] is False


def test_production_no_storage_shape_matches_frozen_no_go():
    value = probes(
        primaryConfigured=False, primaryDevice=None, primaryVerified=False,
        primaryHash=None, secondaryConfigured=False, secondaryDevice=None,
        secondaryVerified=False, secondaryHash=None, restoreRehearsed=False,
        restoredHash=None)
    assert assess_backup_evidence(value) == json.loads((
        ROOT / "contracts/e2-shadow/backup-restore-evidence-no-go.v1.json"
    ).read_text())


@pytest.mark.parametrize("mutation", [
    lambda value: value.update({"extra": True}),
    lambda value: value.update({"sourceDevice": True}),
    lambda value: value.update({"primaryConfigured": 1}),
    lambda value: value.update({"primaryConfigured": False}),
    lambda value: value.update({"primaryVerified": False}),
    lambda value: value.update({"restoreRehearsed": False}),
    lambda value: value.update({"sourceHash": "x" * 64}),
])
def test_malformed_or_inconsistent_probes_fail_closed(mutation):
    value = copy.deepcopy(probes())
    mutation(value)
    with pytest.raises(ValueError):
        assess_backup_evidence(value)


def test_contract_has_no_file_env_network_subprocess_or_runtime_surface():
    source = inspect.getsource(sys.modules[
        "lumi.app.integration.shadow_backup_evidence"]).lower()
    assert all(term not in source for term in (
        "open(", "pathlib", "os.", "environ", "requests", "urllib", "socket",
        "subprocess", "fastapi", "router", "http://", "https://", "write"))


@pytest.mark.parametrize(("path", "value"), [
    (("status",), "NO_GO"),
    (("ready",), False),
    (("independentBackup",), False),
    (("blockers",), ["RESTORE_HASH_MISMATCH"]),
    (("checks", 0, "ready"), False),
    (("executionEffect",), "WRITE"),
    (("actionAllowed",), True),
])
def test_evidence_result_tamper_fails_closed(path, value):
    evidence = copy.deepcopy(assess_backup_evidence(probes()))
    target = evidence
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_backup_evidence(evidence)
