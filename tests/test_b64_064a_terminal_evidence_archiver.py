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


@pytest.fixture(params=("RECONCILED_HOLD", "CLOSED"))
def terminal_sources(tmp_path, monkeypatch, request):
    terminal_state = request.param
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
    receipt_raw = b'{"synthetic":"closed-receipt"}\n'
    if terminal_state == "CLOSED":
        _write(
            activation_root / "journal" / f"{NONCE}.receipt.json",
            receipt_raw, 0o600,
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
    if terminal_state == "CLOSED":
        leaves[f"activation-state/journal/{NONCE}.receipt.json"] = receipt_raw
    unsigned = {
        "schemaVersion": archiver.ARCHIVE_SCHEMA,
        "route": activation.ROUTE,
        "runNonce": NONCE,
        "decisionSha256": DECISION,
        "planSha256": "2" * 64,
        "keyringSha256": "3" * 64,
        "implementationCommit": "a" * 40,
        "archiverSha256": "b" * 64,
        "signedArtifactReleaseCommit": "a" * 40,
        "decisionExpiresAtEpoch": 900,
        "archiveAuthorizedAtEpoch": 1_000,
        "terminalState": terminal_state,
        "terminalReason": (
            None if terminal_state == "CLOSED"
            else "ABNORMAL_EXIT_RECONCILED_NO_RETRY"
        ),
        "terminalReceiptSha256": (
            archiver._sha(receipt_raw[:-1])
            if terminal_state == "CLOSED" else None
        ),
        "resourceState": terminal_state,
        "credentialIssued": terminal_state == "CLOSED",
        "credentialReconciled": True,
        "workspaceAbsent": True,
        "proxyAbsent": True,
        "dumpAbsent": True,
        "restoreAbsent": True,
        "roleLoginState": "DISABLED",
        "credentialState": "ABSENT",
        "activeSessions": 0,
        "containerId": "c" * 64,
        "containerPid": 1234,
        "imageId": "sha256:" + "d" * 64,
        "systemIdentifier": "12345678",
        "archiverCustomerRowsRead": False,
        "terminalRunCustomerRowReadState": (
            "CONFIRMED" if terminal_state == "CLOSED" else "NOT_READ"
        ),
        "hbaChanged": False,
        "authorityIncreased": False,
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
        "terminalState": terminal_state,
        "manifest": manifest,
        "manifestRaw": manifest_raw,
    }


def test_archiver_does_not_invalidate_existing_signed_artifact_closure():
    assert "terminalEvidenceArchiver" not in activation.ARTIFACT_KEYS
    assert "terminalEvidenceArchiver" not in activation.ARTIFACT_PATHS


def test_historical_signed_closure_is_exact_and_restored(tmp_path, monkeypatch):
    historical = tmp_path / ("c" * 40)
    historical.mkdir(mode=0o555)
    original = activation.ARTIFACT_PATHS

    with archiver._signed_artifact_closure(ROOT, historical):
        assert activation.ARTIFACT_PATHS is not original
        assert set(activation.ARTIFACT_PATHS) == activation.ARTIFACT_KEYS
        for key, current in original.items():
            assert activation.ARTIFACT_PATHS[key] == \
                historical / current.relative_to(ROOT)

    assert activation.ARTIFACT_PATHS is original


def test_signed_release_selection_prefers_operational_exact_closure(
    tmp_path, monkeypatch,
):
    operational = tmp_path / ("a" * 40)
    legacy = tmp_path / ("b" * 40)
    operational.mkdir(mode=0o555)
    legacy.mkdir(mode=0o555)
    plan = {"artifactsSha256": {key: "1" * 64 for key in activation.ARTIFACT_KEYS}}
    monkeypatch.setattr(
        activation, "validate_plan", lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(activation, "_decode_json", lambda _raw: {})
    monkeypatch.setattr(archiver, "LEGACY_SIGNED_ARTIFACT_RELEASE", legacy)
    monkeypatch.setattr(
        archiver, "_artifact_paths",
        lambda _operational, candidate: {
            key: candidate / key for key in activation.ARTIFACT_KEYS
        },
    )
    monkeypatch.setattr(
        activation, "_artifact_bytes_and_sha256",
        lambda path: (b"", "1" * 64 if path.parent == operational else "2" * 64),
    )

    assert archiver._select_signed_artifact_release(
        operational_release=operational, activation_plan_raw=b"{}",
    ) == operational


def test_signed_release_selection_falls_back_only_to_fixed_legacy(
    tmp_path, monkeypatch,
):
    operational = tmp_path / ("a" * 40)
    legacy = tmp_path / ("b" * 40)
    operational.mkdir(mode=0o555)
    legacy.mkdir(mode=0o555)
    plan = {"artifactsSha256": {key: "1" * 64 for key in activation.ARTIFACT_KEYS}}
    monkeypatch.setattr(
        activation, "validate_plan", lambda *_args, **_kwargs: plan,
    )
    monkeypatch.setattr(activation, "_decode_json", lambda _raw: {})
    monkeypatch.setattr(archiver, "LEGACY_SIGNED_ARTIFACT_RELEASE", legacy)
    monkeypatch.setattr(
        archiver, "_artifact_paths",
        lambda _operational, candidate: {
            key: candidate / key for key in activation.ARTIFACT_KEYS
        },
    )
    monkeypatch.setattr(
        activation, "_artifact_bytes_and_sha256",
        lambda path: (b"", "1" * 64 if path.parent == legacy else "2" * 64),
    )

    assert archiver._select_signed_artifact_release(
        operational_release=operational, activation_plan_raw=b"{}",
    ) == legacy


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


def test_closed_archive_binds_durable_execution_receipt(terminal_sources):
    entries = archiver._expected_files(
        nonce=NONCE,
        activation_root=terminal_sources["activation"],
        recovery_parent=terminal_sources["recovery"],
        terminal_state="CLOSED",
    )
    assert f"activation-state/journal/{NONCE}.receipt.json" in entries
    assert entries[
        f"activation-state/journal/{NONCE}.receipt.json"
    ][1:] == (0o600, False)


def test_publish_moves_original_components_without_deleting_evidence(
    terminal_sources,
):
    archive, manifest, already = archiver._publish_archive(
        nonce=NONCE, decision_sha256=DECISION,
        manifest_raw=terminal_sources["manifestRaw"],
    )

    assert already is False
    assert manifest["terminalState"] == terminal_sources["terminalState"]
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
    if terminal_sources["terminalState"] == "CLOSED":
        assert (archive / "activation-state" / "journal"
                / f"{NONCE}.receipt.json").read_bytes() == \
            b'{"synthetic":"closed-receipt"}\n'

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


def test_staging_resume_requires_v2_post_expiry_evidence(terminal_sources):
    manifest = terminal_sources["manifest"]
    archiver._require_resumable_staging_manifest(
        manifest, now_epoch=manifest["decisionExpiresAtEpoch"],
    )
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_DECISION_STILL_FRESH",
    ):
        archiver._require_resumable_staging_manifest(
            manifest, now_epoch=manifest["decisionExpiresAtEpoch"] - 1,
        )

    legacy = dict(manifest)
    legacy["schemaVersion"] = archiver.LEGACY_ARCHIVE_SCHEMA
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_LEGACY_STAGING_FORBIDDEN",
    ):
        archiver._require_resumable_staging_manifest(
            legacy, now_epoch=manifest["decisionExpiresAtEpoch"],
        )


def test_v2_manifest_rejects_pre_expiry_archive_authorization(
    terminal_sources,
):
    unsigned = dict(terminal_sources["manifest"])
    unsigned.pop("manifestSha256")
    unsigned["archiveAuthorizedAtEpoch"] = \
        unsigned["decisionExpiresAtEpoch"] - 1
    raw = archiver._canonical({
        **unsigned,
        "manifestSha256": archiver._sha(archiver._canonical(unsigned)),
    }) + b"\n"
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_MANIFEST_INVALID",
    ):
        archiver._decode_manifest(
            raw, nonce=NONCE, decision_sha256=DECISION,
        )


def test_archive_entrypoint_rechecks_existing_staging_expiry(
    terminal_sources, tmp_path, monkeypatch,
):
    staging = terminal_sources["archiveParent"] / "resume.staging"
    final = terminal_sources["archiveParent"] / "resume.final"
    terminal_sources["archiveParent"].mkdir(mode=0o700)
    staging.mkdir(mode=0o700)
    _write(
        staging / archiver.MANIFEST_NAME,
        terminal_sources["manifestRaw"], 0o400,
    )
    lock = tmp_path / "resume.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    release = tmp_path / ("a" * 40)
    release.mkdir(mode=0o555)
    published = []
    now = {"value": 899}

    monkeypatch.setattr(archiver, "_verify_runtime_identity", lambda: release)
    monkeypatch.setattr(
        archiver, "_dormant", lambda: {"status": "DORMANT_VERIFIED"},
    )
    monkeypatch.setattr(
        archiver, "_acquire_lock", lambda: os.open(lock, os.O_RDONLY),
    )
    monkeypatch.setattr(
        archiver.watchdog, "_activation_interlock_status",
        lambda: contextlib.nullcontext(False),
    )
    monkeypatch.setattr(
        archiver, "_archive_names", lambda _nonce: (staging, final),
    )
    monkeypatch.setattr(archiver, "_trusted_now", lambda: now["value"])
    monkeypatch.setattr(archiver, "_component_sources", lambda: {})
    monkeypatch.setattr(
        archiver, "_publish_archive",
        lambda **_kwargs: (
            published.append(True)
            or (final, terminal_sources["manifest"], False)
        ),
    )

    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_DECISION_STILL_FRESH",
    ):
        archiver.archive_terminal_evidence(
            confirm_run_nonce=NONCE,
            confirm_decision_sha256=DECISION,
        )
    assert published == []

    now["value"] = 900
    receipt = archiver.archive_terminal_evidence(
        confirm_run_nonce=NONCE,
        confirm_decision_sha256=DECISION,
    )
    assert published == [True]
    assert receipt["runtimePathsAbsent"] is True


def test_legacy_archive_manifest_remains_idempotently_verifiable(
    terminal_sources,
):
    if terminal_sources["terminalState"] != "RECONCILED_HOLD":
        return
    legacy = dict(terminal_sources["manifest"])
    legacy.pop("manifestSha256")
    legacy.pop("terminalReceiptSha256")
    legacy.pop("archiverCustomerRowsRead")
    legacy.pop("terminalRunCustomerRowReadState")
    legacy.pop("decisionExpiresAtEpoch")
    legacy.pop("archiveAuthorizedAtEpoch")
    legacy["schemaVersion"] = archiver.LEGACY_ARCHIVE_SCHEMA
    legacy["customerRowsRead"] = False
    legacy["signedArtifactReleaseCommit"] = \
        archiver.LEGACY_SIGNED_ARTIFACT_RELEASE.name
    raw = archiver._canonical({
        **legacy,
        "manifestSha256": archiver._sha(archiver._canonical(legacy)),
    }) + b"\n"
    observed = archiver._decode_manifest(
        raw, nonce=NONCE, decision_sha256=DECISION,
    )
    assert observed["schemaVersion"] == archiver.LEGACY_ARCHIVE_SCHEMA

    for field, invalid in (
        ("credentialIssued", True),
        ("terminalReason", None),
    ):
        drifted = dict(legacy)
        drifted[field] = invalid
        drifted_raw = archiver._canonical({
            **drifted,
            "manifestSha256": archiver._sha(archiver._canonical(drifted)),
        }) + b"\n"
        with pytest.raises(
            archiver.ArchiveError,
            match="TERMINAL_ARCHIVE_MANIFEST_INVALID",
        ):
            archiver._decode_manifest(
                drifted_raw, nonce=NONCE, decision_sha256=DECISION,
            )


def test_issued_credential_hold_records_customer_row_reads_as_possible(
    terminal_sources,
):
    if terminal_sources["terminalState"] != "RECONCILED_HOLD":
        return
    unsigned = dict(terminal_sources["manifest"])
    unsigned.pop("manifestSha256")
    unsigned["credentialIssued"] = True
    unsigned["terminalRunCustomerRowReadState"] = "POSSIBLE"
    raw = archiver._canonical({
        **unsigned,
        "manifestSha256": archiver._sha(archiver._canonical(unsigned)),
    }) + b"\n"
    observed = archiver._decode_manifest(
        raw, nonce=NONCE, decision_sha256=DECISION,
    )
    assert observed["terminalRunCustomerRowReadState"] == "POSSIBLE"

    unsigned["terminalRunCustomerRowReadState"] = "NOT_READ"
    drifted = archiver._canonical({
        **unsigned,
        "manifestSha256": archiver._sha(archiver._canonical(unsigned)),
    }) + b"\n"
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_MANIFEST_INVALID",
    ):
        archiver._decode_manifest(
            drifted, nonce=NONCE, decision_sha256=DECISION,
        )


def test_hold_accepts_reconciled_issued_credential_but_rejects_nonterminal(
    monkeypatch,
):
    recovery = SimpleNamespace(
        run_nonce=NONCE, target={}, plan_sha256="2" * 64,
        decision_sha256=DECISION,
        derived_execution_plan_sha256="3" * 64,
    )
    journal = {
        "state": "RECONCILED_HOLD", "retryAllowed": False,
        "receiptSha256": None,
        "reasonCode": "ABNORMAL_EXIT_RECONCILED_NO_RETRY",
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
    observed_journal, observed_resources = archiver._terminal_state(recovery)
    assert observed_journal["state"] == "RECONCILED_HOLD"
    assert observed_resources["credentialIssued"] is True

    resources["credentialIssued"] = False
    journal["state"] = "HOLD"
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_JOURNAL_NOT_TERMINAL",
    ):
        archiver._terminal_state(recovery)


def test_terminal_state_accepts_exact_closed_run(monkeypatch):
    recovery = SimpleNamespace(
        run_nonce=NONCE, target={}, plan_sha256="2" * 64,
        decision_sha256=DECISION,
        derived_execution_plan_sha256="3" * 64,
    )
    journal = {
        "state": "CLOSED", "retryAllowed": False,
        "receiptSha256": "4" * 64, "reasonCode": None,
    }
    resources = {
        "state": "CLOSED", "credentialIssued": True,
        "credentialReconciled": True, "workspaceAbsent": True,
        "proxyAbsent": True, "dumpAbsent": True, "restoreAbsent": True,
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
    checked = []
    monkeypatch.setattr(
        archiver, "_validate_closed_receipt",
        lambda _recovery, *, expected_sha256: checked.append(expected_sha256),
    )

    observed_journal, observed_resources = archiver._terminal_state(recovery)
    assert observed_journal["receiptSha256"] == "4" * 64
    assert observed_resources["state"] == "CLOSED"
    assert checked == ["4" * 64]


@pytest.mark.parametrize("terminal_state", ["CLOSED", "RECONCILED_HOLD"])
def test_terminal_archive_waits_until_consumed_decision_expires(
    terminal_state,
):
    recovery = SimpleNamespace(decision_expires_at_epoch=1_000)
    journal = {"state": terminal_state}

    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_DECISION_STILL_FRESH",
    ):
        archiver._require_terminal_decision_expired(
            recovery, journal, now_epoch=999,
        )

    archiver._require_terminal_decision_expired(
        recovery, journal, now_epoch=1_000,
    )


def test_fresh_terminal_decision_cannot_reach_archive_publication(
    tmp_path, monkeypatch,
):
    lock = tmp_path / "archive.lock"
    lock.write_bytes(b"")
    lock.chmod(0o600)
    activation_root = tmp_path / "activation"
    final = tmp_path / "final"
    staging = tmp_path / "staging"
    release = tmp_path / ("a" * 40)
    release.mkdir(mode=0o555)
    recovery = SimpleNamespace(decision_expires_at_epoch=1_000)
    published = []

    class Journal:
        def __init__(self, *_args):
            pass

        def acquire_execution_lock(self):
            return os.open(lock, os.O_RDONLY)

    monkeypatch.setattr(archiver, "_verify_runtime_identity", lambda: release)
    monkeypatch.setattr(archiver, "_dormant", lambda: {})
    monkeypatch.setattr(
        archiver, "_acquire_lock", lambda: os.open(lock, os.O_RDONLY),
    )
    monkeypatch.setattr(
        archiver.watchdog, "_activation_interlock_status",
        lambda: contextlib.nullcontext(False),
    )
    monkeypatch.setattr(archiver, "_archive_names", lambda _nonce: (
        staging, final,
    ))
    monkeypatch.setattr(archiver, "_path_exists", lambda _path: False)
    monkeypatch.setattr(
        archiver.watchdog, "_load_recovery_package", lambda: {"package": True},
    )
    monkeypatch.setattr(
        archiver, "_verified_recovery",
        lambda *_args, **_kwargs: (recovery, release, 999),
    )
    monkeypatch.setattr(activation, "ActivationJournal", Journal)
    monkeypatch.setattr(
        archiver, "_terminal_state",
        lambda _recovery: (
            {"state": "CLOSED"}, {"state": "CLOSED"},
        ),
    )
    monkeypatch.setattr(
        archiver, "_publish_archive",
        lambda **_kwargs: published.append(True),
    )

    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_DECISION_STILL_FRESH",
    ):
        archiver.archive_terminal_evidence(
            confirm_run_nonce=NONCE,
            confirm_decision_sha256=DECISION,
        )
    assert published == []


def _closed_receipt(recovery, **overrides):
    value = {
        "schemaVersion": activation.EXECUTION_RECEIPT_SCHEMA,
        "route": activation.ROUTE,
        "environment": recovery.environment,
        "runNonce": recovery.run_nonce,
        "planSha256": recovery.plan_sha256,
        "decisionSha256": recovery.decision_sha256,
        "status": "COMPLETED_DORMANT_VERIFIED",
        "archiveBytes": 4096,
        "archiveSha256": "5" * 64,
        "catalogEquality": True,
        "tableEquality": True,
        "credentialIssued": True,
        "credentialRevoked": True,
        "sourceSessionClosed": True,
        "readerLoginState": "DISABLED",
        "readerCredentialState": "ABSENT",
        "readerActiveSessions": 0,
        "registeredWorkspaceAbsent": True,
        "dumpContainerAbsent": True,
        "restoreContainerAbsent": True,
        "containerTmpfsLifetimesEnded": True,
        "productionDataRetained": False,
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }
    value.update(overrides)
    return value


def test_closed_receipt_is_canonical_validated_and_digest_bound(
    tmp_path, monkeypatch,
):
    journal_root = tmp_path / "journal"
    journal_root.mkdir(mode=0o700)
    recovery = SimpleNamespace(
        environment="PRODUCTION", run_nonce=NONCE,
        plan_sha256="2" * 64, decision_sha256=DECISION,
        limits={"maximumArchiveBytes": 16 * 1024 * 1024},
    )
    value = _closed_receipt(recovery)
    canonical = archiver._canonical(value)
    receipt = journal_root / f"{NONCE}.receipt.json"
    _write(receipt, canonical + b"\n", 0o600)
    monkeypatch.setattr(activation, "PRODUCTION_JOURNAL_ROOT", journal_root)

    observed = archiver._validate_closed_receipt(
        recovery, expected_sha256=archiver._sha(canonical),
    )
    assert observed == value
    with pytest.raises(
        archiver.ArchiveError,
        match="TERMINAL_ARCHIVE_RECEIPT_DIGEST_MISMATCH",
    ):
        archiver._validate_closed_receipt(
            recovery, expected_sha256="9" * 64,
        )


@pytest.mark.parametrize("raw", [
    b'{"duplicate":1,"duplicate":2}\n',
    b'{not-json}\n',
])
def test_closed_receipt_rejects_malformed_or_duplicate_json(
    tmp_path, monkeypatch, raw,
):
    journal_root = tmp_path / "journal"
    journal_root.mkdir(mode=0o700)
    recovery = SimpleNamespace(
        environment="PRODUCTION", run_nonce=NONCE,
        plan_sha256="2" * 64, decision_sha256=DECISION,
        limits={"maximumArchiveBytes": 16 * 1024 * 1024},
    )
    _write(journal_root / f"{NONCE}.receipt.json", raw, 0o600)
    monkeypatch.setattr(activation, "PRODUCTION_JOURNAL_ROOT", journal_root)
    with pytest.raises(
        archiver.ArchiveError, match="TERMINAL_ARCHIVE_RECEIPT_INVALID",
    ):
        archiver._validate_closed_receipt(
            recovery, expected_sha256="9" * 64,
        )


@pytest.mark.parametrize("override", [
    {"runNonce": "wrong_nonce_1234"},
    {"decisionSha256": "8" * 64},
    {"catalogEquality": False},
    {"credentialRevoked": False},
])
def test_closed_receipt_rejects_binding_or_closure_drift(
    tmp_path, monkeypatch, override,
):
    journal_root = tmp_path / "journal"
    journal_root.mkdir(mode=0o700)
    recovery = SimpleNamespace(
        environment="PRODUCTION", run_nonce=NONCE,
        plan_sha256="2" * 64, decision_sha256=DECISION,
        limits={"maximumArchiveBytes": 16 * 1024 * 1024},
    )
    canonical = archiver._canonical(_closed_receipt(recovery, **override))
    _write(
        journal_root / f"{NONCE}.receipt.json", canonical + b"\n", 0o600,
    )
    monkeypatch.setattr(activation, "PRODUCTION_JOURNAL_ROOT", journal_root)
    with pytest.raises(
        archiver.ArchiveError, match="TERMINAL_ARCHIVE_RECEIPT_INVALID",
    ):
        archiver._validate_closed_receipt(
            recovery, expected_sha256=archiver._sha(canonical),
        )
