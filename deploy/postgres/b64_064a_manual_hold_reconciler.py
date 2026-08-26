#!/usr/bin/env python3
"""Fixed-scope cleanup-only reconciliation of one confirmed 064A HOLD.

This command accepts only the operator's exact nonce and decision-digest
confirmations.  All package, target, time and resource paths are fixed by the
signed recovery package and immutable release.  It has no execute or lease
authority and is valid only after the signed decision has expired.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path
from typing import Any

import b64_064a_activation_entrypoint as activation
import b64_snapshot_reader_watchdog as watchdog


RELEASE_BASE = Path(
    "/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a"
)


class ReconcileError(activation.ActivationError):
    """Closed reason code safe for the operator receipt."""


def _reason(exc: BaseException) -> str:
    if (isinstance(exc, (ReconcileError, activation.ActivationError,
                         watchdog.WatchdogError))
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "MANUAL_HOLD_RECONCILE_UNEXPECTED_FAILURE"


def _verify_runtime_identity() -> Path:
    if os.geteuid() != 0:
        raise ReconcileError("MANUAL_HOLD_RECONCILE_ROOT_REQUIRED")
    script = Path(__file__).resolve()
    try:
        release = script.parents[2]
    except IndexError as exc:
        raise ReconcileError(
            "MANUAL_HOLD_RECONCILE_RELEASE_IDENTITY_INVALID"
        ) from exc
    if (release.parent != RELEASE_BASE
            or re.fullmatch(r"[0-9a-f]{40}", release.name) is None
            or activation.PROJECT_ROOT != release
            or Path(watchdog.__file__).resolve().parents[2] != release):
        raise ReconcileError(
            "MANUAL_HOLD_RECONCILE_RELEASE_IDENTITY_INVALID"
        )
    try:
        release_info = os.lstat(release)
        script_info = os.lstat(script)
    except OSError as exc:
        raise ReconcileError("MANUAL_HOLD_RECONCILE_RELEASE_UNSAFE") from exc
    if (not stat.S_ISDIR(release_info.st_mode)
            or stat.S_ISLNK(release_info.st_mode)
            or release_info.st_uid != 0 or release_info.st_gid != 0
            or stat.S_IMODE(release_info.st_mode) != 0o555
            or not stat.S_ISREG(script_info.st_mode)
            or script_info.st_uid != 0 or script_info.st_gid != 0
            or stat.S_IMODE(script_info.st_mode) != 0o444
            or script_info.st_nlink != 1):
        raise ReconcileError("MANUAL_HOLD_RECONCILE_RELEASE_UNSAFE")
    return release


def reconcile(
    *, confirm_run_nonce: str, confirm_decision_sha256: str,
) -> dict[str, Any]:
    _verify_runtime_identity()
    result = watchdog.watchdog_with_cleanup_recovery(
        container_name=activation.PRODUCTION_CONTAINER,
        expected_image_id=activation.PRODUCTION_IMAGE_ID,
        expected_volume_name=watchdog.PRODUCTION_VOLUME,
        expected_server_version_num=170011,
        expected_system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
        manual_hold=True,
        confirm_run_nonce=confirm_run_nonce,
        confirm_decision_sha256=confirm_decision_sha256,
    )
    if (result.get("status")
            != "DORMANT_VERIFIED_MANUAL_HOLD_RECONCILED"
            or result.get("recoveryStatus")
            != "ACTIVATION_RECONCILED_HOLD"
            or result.get("recoveryRunNonce") != confirm_run_nonce
            or result.get("automaticRetryAllowed") is not False
            or result.get("actionAllowed") is not False):
        raise ReconcileError("MANUAL_HOLD_RECONCILE_RESULT_INVALID")
    return {
        "schemaVersion": "b64-064a-manual-hold-reconcile-receipt.v1",
        "route": activation.ROUTE,
        "status": "MANUAL_HOLD_RECONCILED_DORMANT_VERIFIED",
        "runNonce": confirm_run_nonce,
        "decisionSha256": confirm_decision_sha256,
        "credentialState": result["credentialState"],
        "roleLoginState": result["roleLoginState"],
        "activeSessions": result["activeSessions"],
        "reconcilerCustomerRowsRead": False,
        "hbaChanged": False,
        "authorityIncreased": False,
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--confirm-run-nonce", required=True)
    parser.add_argument("--confirm-decision-sha256", required=True)
    args = parser.parse_args()
    try:
        receipt = reconcile(
            confirm_run_nonce=args.confirm_run_nonce,
            confirm_decision_sha256=args.confirm_decision_sha256,
        )
        code = 0
    except BaseException as exc:
        receipt = {
            "schemaVersion": "b64-064a-manual-hold-reconcile-receipt.v1",
            "route": activation.ROUTE,
            "status": "NO_GO",
            "reason": _reason(exc),
            "reconcilerCustomerRowsRead": False,
            "hbaChanged": False,
            "authorityIncreased": False,
            "automaticRetryAllowed": False,
            "actionAllowed": False,
        }
        code = 3
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
