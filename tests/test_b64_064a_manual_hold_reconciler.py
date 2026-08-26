from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
POSTGRES = ROOT / "deploy/postgres"
sys.path.insert(0, str(POSTGRES))

activation = importlib.import_module("b64_064a_activation_entrypoint")
manual = importlib.import_module("b64_064a_manual_hold_reconciler")
watchdog = importlib.import_module("b64_snapshot_reader_watchdog")


def _watchdog_result(nonce: str):
    return {
        "status": "DORMANT_VERIFIED_MANUAL_HOLD_RECONCILED",
        "recoveryStatus": "ACTIVATION_RECONCILED_HOLD",
        "recoveryRunNonce": nonce,
        "credentialState": "ABSENT", "roleLoginState": "DISABLED",
        "activeSessions": 0, "automaticRetryAllowed": False,
        "actionAllowed": False,
    }


def test_manual_reconciler_is_in_signed_artifact_closure():
    assert activation.ARTIFACT_PATHS["manualHoldReconciler"] == \
        POSTGRES / "b64_064a_manual_hold_reconciler.py"
    assert "manualHoldReconciler" in activation.ARTIFACT_KEYS


def test_reconcile_uses_only_fixed_production_scope(monkeypatch, tmp_path):
    nonce = "production_nonce_1234"
    decision_sha = "3" * 64
    monkeypatch.setattr(manual, "_verify_runtime_identity", lambda: tmp_path)
    observed = {}

    def reconcile(**kwargs):
        observed.update(kwargs)
        return _watchdog_result(nonce)

    monkeypatch.setattr(watchdog, "watchdog_with_cleanup_recovery", reconcile)
    result = manual.reconcile(
        confirm_run_nonce=nonce,
        confirm_decision_sha256=decision_sha,
    )

    assert observed == {
        "container_name": activation.PRODUCTION_CONTAINER,
        "expected_image_id": activation.PRODUCTION_IMAGE_ID,
        "expected_volume_name": watchdog.PRODUCTION_VOLUME,
        "expected_server_version_num": 170011,
        "expected_system_identifier": activation.PRODUCTION_SYSTEM_IDENTIFIER,
        "manual_hold": True,
        "confirm_run_nonce": nonce,
        "confirm_decision_sha256": decision_sha,
    }
    assert result["status"] == "MANUAL_HOLD_RECONCILED_DORMANT_VERIFIED"
    assert result["reconcilerCustomerRowsRead"] is False
    assert result["hbaChanged"] is False
    assert result["authorityIncreased"] is False
    assert result["actionAllowed"] is False


@pytest.mark.parametrize(
    "change",
    [
        {"status": "DORMANT_VERIFIED_RECOVERY_RECONCILED_HOLD"},
        {"recoveryStatus": "ACTIVATION_RECONCILED_HOLD_OTHER"},
        {"recoveryRunNonce": "different_nonce_1234"},
        {"automaticRetryAllowed": True},
        {"actionAllowed": True},
    ],
)
def test_reconcile_rejects_non_exact_cleanup_receipt(
    monkeypatch, tmp_path, change,
):
    nonce = "production_nonce_1234"
    value = {**_watchdog_result(nonce), **change}
    monkeypatch.setattr(manual, "_verify_runtime_identity", lambda: tmp_path)
    monkeypatch.setattr(
        watchdog, "watchdog_with_cleanup_recovery", lambda **_kwargs: value,
    )
    with pytest.raises(
        manual.ReconcileError, match="MANUAL_HOLD_RECONCILE_RESULT_INVALID",
    ):
        manual.reconcile(
            confirm_run_nonce=nonce,
            confirm_decision_sha256="3" * 64,
        )
