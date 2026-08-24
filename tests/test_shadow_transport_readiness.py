import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
LUMI_ROOT = ROOT / "lumi"
for path in (LUMI_ROOT, ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from lumi.app.integration.shadow_public_keyring import initial_keyring
from lumi.app.integration.shadow_backup_evidence import assess_backup_evidence
from lumi.app.integration.shadow_replay_ledger import empty_snapshot
from lumi.app.integration.shadow_transport_readiness import (
    CHECKS, PROBES_SCHEMA, assess_readiness,
)

SCRIPT_PATH = LUMI_ROOT / "scripts/check_shadow_transport_readiness.py"
SPEC = importlib.util.spec_from_file_location("shadow_transport_probe", SCRIPT_PATH)
PROBE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(PROBE)
NOW = 1786424405


def probes(**changes):
    value = {"schemaVersion": PROBES_SCHEMA}
    value.update({field: True for _, field, _ in CHECKS})
    value.update(changes)
    return value


def test_all_satisfied_is_go_but_still_non_executing():
    result = assess_readiness(probes())
    assert result["status"] == "GO" and result["ready"] is True
    assert result["blockers"] == []
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False


@pytest.mark.parametrize(("field", "blocker"), [
    (field, blocker) for _, field, blocker in CHECKS
])
def test_each_prerequisite_independently_blocks_go(field, blocker):
    changes = {field: False}
    if field == "keyringConfigured":
        changes.update(keyringValid=False, activeKeyAvailable=False)
    elif field == "keyringValid":
        changes.update(activeKeyAvailable=False)
    elif field == "replayPathConfigured":
        changes.update(replayParentSafe=False, replayStateValid=False)
    elif field == "replayParentSafe":
        changes.update(replayStateValid=False)
    result = assess_readiness(probes(**changes))
    assert result["status"] == "NO_GO" and result["ready"] is False
    assert blocker in result["blockers"]


@pytest.mark.parametrize("mutation", [
    lambda value: value.update({"extra": True}),
    lambda value: value.update({"schemaVersion": "shadow-transport-probes.v2"}),
    lambda value: value.update({"ed25519Dependency": 1}),
    lambda value: value.update({"keyringValid": False, "activeKeyAvailable": True}),
    lambda value: value.update({"keyringConfigured": False, "keyringValid": True}),
    lambda value: value.update({"replayParentSafe": False, "replayStateValid": True}),
])
def test_malformed_or_inconsistent_probes_fail_closed(mutation):
    value = probes()
    mutation(value)
    with pytest.raises(ValueError):
        assess_readiness(value)


def test_empty_environment_matches_frozen_no_go_fixture_without_state(tmp_path):
    before = list(tmp_path.iterdir())
    expected = json.loads((
        ROOT / "contracts/e2-shadow/transport-readiness-no-go.v1.json").read_text())
    result = PROBE.probe_runtime(
        environment={}, now_epoch=NOW, dependency_available=False)
    assert result == expected
    assert list(tmp_path.iterdir()) == before


def test_configured_safe_files_can_satisfy_file_probes_without_writes(tmp_path):
    keyring = tmp_path / "keyring.json"
    value = initial_keyring(
        key_id="kairos-shadow-v1", public_key=bytes(range(32)),
        activated_at=NOW - 1, valid_until=NOW + 100)
    keyring.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    keyring.chmod(0o644)
    replay_dir = tmp_path / "replay"
    replay_dir.mkdir(mode=0o700)
    replay = replay_dir / "ledger.json"
    replay.write_text(json.dumps(empty_snapshot(capacity=10)))
    replay.chmod(0o600)
    before = {path: path.read_bytes() for path in (keyring, replay)}
    environment = {
        "LUMI_E2_SHADOW_KEYRING": str(keyring),
        "LUMI_E2_SHADOW_REPLAY_FILE": str(replay),
    }
    result = PROBE.probe_runtime(
        environment=environment, now_epoch=NOW, dependency_available=True)
    ready = {item["checkId"]: item["ready"] for item in result["checks"]}
    assert all(ready[item] for item in (
        "ED25519_DEPENDENCY", "KEYRING_CONFIGURED", "KEYRING_VALID",
        "ACTIVE_KEY", "REPLAY_PATH_CONFIGURED", "REPLAY_PARENT_SAFE",
        "REPLAY_STATE_VALID"))
    assert result["status"] == "NO_GO"
    assert result == json.loads((
        ROOT / "contracts/e2-shadow/transport-readiness-replay-ready-no-go.v1.json"
    ).read_text())
    assert {path: path.read_bytes() for path in (keyring, replay)} == before
    assert not replay.with_suffix(".json.lock").exists()


def test_production_keyring_only_state_matches_frozen_no_go_fixture(tmp_path):
    expected = json.loads((
        ROOT / "contracts/e2-shadow/transport-readiness-keyring-ready-no-go.v1.json"
    ).read_text())
    keyring = tmp_path / "keyring.json"
    value = initial_keyring(
        key_id="kairos-shadow-v1", public_key=bytes(range(32)),
        activated_at=NOW - 1, valid_until=NOW + 100)
    keyring.write_text(json.dumps(value, sort_keys=True, separators=(",", ":")))
    environment = {"LUMI_E2_SHADOW_KEYRING": str(keyring)}
    result = PROBE.probe_runtime(
        environment=environment, now_epoch=NOW, dependency_available=True)
    assert result == expected
    assert len(result["blockers"]) == 8
    assert result["status"] == "NO_GO" and result["actionAllowed"] is False


def test_only_narrow_root_group_ready_evidence_satisfies_backup_probe(tmp_path):
    digest = "a" * 64
    evidence = assess_backup_evidence({
        "schemaVersion": "shadow-backup-restore-probes.v1",
        "sourceDevice": 10,
        "primaryConfigured": True, "primaryDevice": 20,
        "secondaryConfigured": True, "secondaryDevice": 30,
        "primaryVerified": True, "secondaryVerified": True,
        "restoreRehearsed": True,
        "sourceHash": digest, "primaryHash": digest,
        "secondaryHash": digest, "restoredHash": digest,
    })
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(evidence, sort_keys=True, separators=(",", ":")))
    path.chmod(0o640)
    environment = {"LUMI_E2_SHADOW_BACKUP_EVIDENCE": str(path)}
    assert PROBE._independent_backup_evidence(environment) is True
    path.chmod(0o644)
    assert PROBE._independent_backup_evidence(environment) is False


def test_missing_no_go_corrupt_and_symlink_evidence_remain_blocked(tmp_path):
    missing = {"LUMI_E2_SHADOW_BACKUP_EVIDENCE": str(tmp_path / "missing")}
    assert PROBE._independent_backup_evidence(missing) is False
    no_go = ROOT / "contracts/e2-shadow/backup-restore-evidence-no-go.v1.json"
    local = tmp_path / "no-go.json"
    local.write_bytes(no_go.read_bytes())
    local.chmod(0o640)
    assert PROBE._independent_backup_evidence(
        {"LUMI_E2_SHADOW_BACKUP_EVIDENCE": str(local)}) is False
    local.write_text("{")
    assert PROBE._independent_backup_evidence(
        {"LUMI_E2_SHADOW_BACKUP_EVIDENCE": str(local)}) is False
    outside = tmp_path / "outside"
    outside.write_text("{}")
    link = tmp_path / "link"
    link.symlink_to(outside)
    assert PROBE._independent_backup_evidence(
        {"LUMI_E2_SHADOW_BACKUP_EVIDENCE": str(link)}) is False


def test_readiness_has_no_directory_device_fallback():
    source = Path(SCRIPT_PATH).read_text()
    assert "KAIROS_E2_BACKUP_PRIMARY" not in source
    assert "KAIROS_E2_BACKUP_SECONDARY" not in source
    assert "primary.stat().st_dev" not in source
    assert "secondary.stat().st_dev" not in source


def test_cli_is_stdout_only_no_go_and_creates_no_default_state(tmp_path):
    environment = {"PYTHONPATH": str(LUMI_ROOT), "PATH": os.environ["PATH"]}
    process = subprocess.run(
        [str(ROOT / "lumi/venv/bin/python"), str(SCRIPT_PATH)],
        cwd=tmp_path, env=environment, text=True, capture_output=True, check=False)
    assert process.returncode == 1 and process.stderr == ""
    result = json.loads(process.stdout)
    assert result["status"] == "NO_GO" and result["actionAllowed"] is False
    assert list(tmp_path.iterdir()) == []
