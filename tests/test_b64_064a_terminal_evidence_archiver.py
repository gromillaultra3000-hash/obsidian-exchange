from __future__ import annotations

import contextlib
import importlib
import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

archiver = importlib.import_module("b64_064a_terminal_evidence_archiver")
activation = importlib.import_module("b64_064a_activation_entrypoint")
executor = importlib.import_module("b64_064a_activation_executor")


NONCE = "terminal_nonce_1234"
DECISION = "1" * 64


def _write(path: Path, raw: bytes, mode: int) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


@pytest.fixture
def terminal_sources(tmp_path, monkeypatch):
    backup = tmp_path / "backups"
    backup.mkdir(mode=0o755)
    archive_parent = backup / "terminal"
    recovery = tmp_path / "etc"
    recovery.mkdir(mode=0o700)
    activation_root = tmp_path / "var" / "activation"
    activation_root.parent.mkdir(mode=0o700)
    activation_root.mkdir(mode=0o700)
    for name in ("journal", "resources", "workspace", "proxy"):
        (activation_root / name).mkdir(mode=0o700)

    package = recovery / archiver.watchdog.RECOVERY_PACKAGE_NAME
    package.mkdir(mode=0o700)
    package_files = {
        "keyring.json": b"keyring\n",
        "decision.json": b"decision\n",
        "activation-plan.json": b"plan\n",
        "manifest.json": b"recovery manifest\n",
    }
    for name, raw in package_files.items():
        _write(package / name, raw, 0o400)
    package.chmod(0o500)
    _write(
        recovery / archiver.watchdog.RECOVERY_REQUEST_NAME,
        b"recovery request\n", 0o400,
    )
    _write(
        recovery / archiver.launcher.LAUNCH_REQUEST_NAME,
        b"launch request\n", 0o400,
    )
    _write(
        activation_root / "journal" / f"{NONCE}.json",
        b"journal\n", 0o600,
    )
    _write(
        activation_root / "journal" / f".{NONCE}.lock",
        b"", 0o600,
    )
    _write(
        activation_root / "resources" / f"{NONCE}.resources.json",
        b"resources\n", 0o600,
    )

    monkeypatch.setattr(archiver, "BACKUP_BASE", backup)
    monkeypatch.setattr(archiver, "ARCHIVE_PARENT", archive_parent)
    monkeypatch.setattr(archiver, "RECOVERY_PARENT", recovery)
    monkeypatch.setattr(archiver, "ACTIVATION_ROOT", activation_root)

    leaves = {
        "recovery-package/keyring.json": b"keyring\n",
        "recovery-package/decision.json": b"decision\n",
        "recovery-package/activation-plan.json": b"plan\n",
        "recovery-package/manifest.json": b"recovery manifest\n",
        "recovery-request.json": b"recovery request\n",
        "launch-request.json": b"launch request\n",
        f"activation-state/journal/{NONCE}.json": b"journal\n",
        f"activation-state/journal/.{NONCE}.lock": b"",
        f"activation-state/resources/{NONCE}.resources.json": b"resources\n",
    }
    unsigned = {
        "schemaVersion": archiver.ARCHIVE_SCHEMA,
        "route": activation.ROUTE,
        "runNonce": NONCE,
        "decisionSha256": DECISION,
        "implementationCommit": "a" * 40,
        "archiverSha256": "b" * 64,
        "terminalState": "RECONCILED_HOLD",
        "resourceState": "RECONCILED_HOLD",
        "credentialIssued": False,
        "credentialReconciled": True,
        "automaticRetryAllowed": False,
        "activationRetryAllowed": False,
        "sourceComponents": sorted(archiver.COMPONENTS),
        "files": {
            name: {
                "sha256": archiver._sha(raw),
                "size": len(raw),
                "mode": (
                    0o600 if name.startswith("activation-state/") else 0o400
                ),
            }
            for name, raw in leaves.items()
        },
    }
    manifest = {
        **unsigned,
        "manifestSha256": archiver._sha(archiver._canonical(unsigned)),
    }
    manifest_raw = archiver._canonical(manifest) + b"\n"
    return {
        "activation": activation_root,
        "recovery": recovery,
        "archiveParent": archive_parent,
        "manifestRaw": manifest_raw,
    }


def test_archiver_does_not_invalidate_existing_signed_artifact_closure():
    assert "terminalEvidenceArchiver" not in activation.ARTIFACT_KEYS
    assert "terminalEvidenceArchiver" not in activation.ARTIFACT_PATHS


def test_parser_requires_both_exact_confirmations():
    parser = archiver.parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])
    value = parser.parse_args([
        "--confirm-run-nonce", NONCE,
        "--confirm-decision-sha256", DECISION,
    ])
    assert value.confirm_run_nonce == NONCE
    assert value.confirm_decision_sha256 == DECISION


def test_publish_moves_original_components_without_deleting_evidence(
    terminal_sources,
):
    archive, manifest, already = archiver._publish_archive(
        nonce=NONCE, decision_sha256=DECISION,
        manifest_raw=terminal_sources["manifestRaw"],
    )

    assert already is False
    assert manifest["terminalState"] == "RECONCILED_HOLD"
    assert stat.S_IMODE(archive.stat().st_mode) == 0o500
    assert set(path.name for path in archive.iterdir()) == {
        *archiver.COMPONENTS, archiver.MANIFEST_NAME,
    }
    assert not terminal_sources["activation"].exists()
    assert not (
        terminal_sources["recovery"]
        / archiver.watchdog.RECOVERY_PACKAGE_NAME
    ).exists()
    assert (archive / "activation-state" / "journal"
            / f"{NONCE}.json").read_bytes() == b"journal\n"
    assert (archive / "recovery-package" / "decision.json").read_bytes() \
        == b"decision\n"

    repeated, repeated_manifest, repeated_already = archiver._publish_archive(
        nonce=NONCE, decision_sha256=DECISION,
        manifest_raw=terminal_sources["manifestRaw"],
    )
    assert repeated == archive
    assert repeated_manifest == manifest
    assert repeated_already is True


@pytest.mark.parametrize("failure_point", [
    "after_manifest",
    "after_activation-state_move",
    "after_launch-request.json_move",
    "after_recovery-request.json_move",
    "after_recovery-package_move",
    "after_archive_publish",
])
def test_every_crash_prefix_resumes_to_one_verified_archive(
    terminal_sources, failure_point,
):
    def fail(point):
        if point == failure_point:
            raise archiver.ArchiveError("INJECTED_ARCHIVE_CRASH")

    with pytest.raises(
        archiver.ArchiveError, match="INJECTED_ARCHIVE_CRASH",
    ):
        archiver._publish_archive(
            nonce=NONCE, decision_sha256=DECISION,
            manifest_raw=terminal_sources["manifestRaw"], fault=fail,
        )

    archive, manifest, _already = archiver._publish_archive(
        nonce=NONCE, decision_sha256=DECISION,
        manifest_raw=terminal_sources["manifestRaw"],
    )
    assert manifest["manifestSha256"]
    assert stat.S_IMODE(archive.stat().st_mode) == 0o500
    assert not terminal_sources["activation"].exists()
    assert not any(
        (terminal_sources["recovery"] / name).exists()
        for name in (
            archiver.watchdog.RECOVERY_PACKAGE_NAME,
            archiver.watchdog.RECOVERY_REQUEST_NAME,
            archiver.launcher.LAUNCH_REQUEST_NAME,
        )
    )


def test_staging_manifest_drift_is_rejected(terminal_sources):
    staging, _final = archiver._archive_names(NONCE)
    terminal_sources["archiveParent"].mkdir(mode=0o700)
    staging.mkdir(mode=0o700)
    _write(staging / archiver.MANIFEST_NAME, b"{}\n", 0o400)
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_STAGING_MANIFEST_MISMATCH",
    ):
        archiver._publish_archive(
            nonce=NONCE, decision_sha256=DECISION,
            manifest_raw=terminal_sources["manifestRaw"],
        )


def test_terminal_state_rejects_nonterminal_or_issued_credential(monkeypatch):
    recovery = SimpleNamespace(
        run_nonce=NONCE, target={}, plan_sha256="2" * 64,
        decision_sha256=DECISION,
        derived_execution_plan_sha256="3" * 64,
    )
    journal = {
        "state": "RECONCILED_HOLD", "retryAllowed": False,
        "receiptSha256": None,
    }
    resources = {
        "state": "RECONCILED_HOLD",
        "credentialIssued": False, "credentialReconciled": True,
        "workspaceAbsent": True, "proxyAbsent": True,
        "dumpAbsent": True, "restoreAbsent": True,
        "workspaceName": "workspace", "proxyName": "proxy",
        "dumpName": "dump", "restoreName": "restore",
    }

    class Journal:
        def __init__(self, *_args):
            pass

        def inspect(self):
            return dict(journal)

    class ResourceJournal:
        def __init__(self, **_kwargs):
            pass

        def inspect_optional(self):
            return dict(resources)

    monkeypatch.setattr(activation, "ActivationJournal", Journal)
    monkeypatch.setattr(executor, "ExecutorResourceJournal", ResourceJournal)
    monkeypatch.setattr(executor, "_path_entry_absent", lambda _path: True)
    monkeypatch.setattr(executor, "_inspect_container", lambda _name: None)

    observed_journal, observed_resources = archiver._terminal_state(recovery)
    assert observed_journal["state"] == "RECONCILED_HOLD"
    assert observed_resources["credentialIssued"] is False

    resources["credentialIssued"] = True
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_RESOURCES_NOT_RECONCILED_HOLD",
    ):
        archiver._terminal_state(recovery)

    resources["credentialIssued"] = False
    journal["state"] = "HOLD"
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_JOURNAL_NOT_RECONCILED_HOLD",
    ):
        archiver._terminal_state(recovery)
