#!/usr/bin/env python3
"""Fail-closed boot gate for an exact PostgreSQL container transition.

The gate derives the previous runtime identity only from the root-controlled
HBA recovery journal, performs the allowlisted atomic rebind, and then requires
the snapshot-reader authority to be fully dormant. It accepts no credentials.
"""
from __future__ import annotations

import argparse
import json
import os
import re
from typing import Any

from b64_snapshot_reader_runtime_rebind import (
    POSTGRES_17_11_IMAGE_ID,
    PRODUCTION_CONTAINER,
    PRODUCTION_IMAGE_TRANSITIONS,
    PRODUCTION_SYSTEM_IDENTIFIER,
    PRODUCTION_VOLUME,
    RebindError,
    _host_lock,
    _open_bundle,
    _safe_reason,
    _validate_journal,
    inspect_container,
    rebind_runtime,
)
from b64_snapshot_reader_watchdog import watchdog_once


class TransitionGateError(RuntimeError):
    """Closed operational reason emitted without journal or credential data."""


def _previous_binding(
    container: dict[str, Any], expected_system_identifier: str
) -> tuple[str, str]:
    pgdata_fd, state_fd, journal, _pending, _ownership_rebind = _open_bundle(container)
    try:
        previous_container_id = str(journal.get("containerId", ""))
        previous_image_id = str(journal.get("containerImageId", ""))
        if re.fullmatch(r"sha256:[0-9a-f]{64}", previous_image_id) is None:
            raise TransitionGateError("JOURNAL_IMAGE_BINDING_INVALID")
        _validate_journal(
            journal,
            allowed_container_ids={previous_container_id},
            allowed_image_ids={previous_image_id},
            expected_system_identifier=expected_system_identifier,
        )
        return previous_container_id, previous_image_id
    finally:
        os.close(state_fd)
        os.close(pgdata_fd)


def transition_gate_once(
    *,
    container_name: str = PRODUCTION_CONTAINER,
    expected_image_id: str = POSTGRES_17_11_IMAGE_ID,
    expected_volume_name: str = PRODUCTION_VOLUME,
    expected_server_version_num: int = 170011,
    expected_system_identifier: str = PRODUCTION_SYSTEM_IDENTIFIER,
    allow_contract_container: bool = False,
    apply: bool = False,
) -> dict[str, Any]:
    with _host_lock():
        container = inspect_container(
            container_name,
            expected_image_id=expected_image_id,
            expected_volume_name=expected_volume_name,
            allow_contract_container=allow_contract_container,
        )
        previous_container_id, previous_image_id = _previous_binding(
            container, expected_system_identifier
        )
        if (previous_image_id, expected_image_id) not in PRODUCTION_IMAGE_TRANSITIONS:
            raise TransitionGateError("JOURNAL_IMAGE_TRANSITION_NOT_ALLOWED")
        rebound = rebind_runtime(
            container_name=container_name,
            expected_image_id=expected_image_id,
            expected_volume_name=expected_volume_name,
            previous_container_id=previous_container_id,
            previous_image_id=previous_image_id,
            expected_server_version_num=expected_server_version_num,
            expected_system_identifier=expected_system_identifier,
            apply=apply,
            allow_contract_container=allow_contract_container,
            host_lock_held=True,
        )
    if not apply and rebound["status"] != "ALREADY_RUNTIME_BOUND":
        raise TransitionGateError("TRANSITION_GATE_APPLY_REQUIRED")
    dormant = watchdog_once(
        container_name=container_name,
        expected_image_id=expected_image_id,
        expected_volume_name=expected_volume_name,
        expected_server_version_num=expected_server_version_num,
        expected_system_identifier=expected_system_identifier,
        allow_contract_container=allow_contract_container,
        require_dormant=True,
    )
    if (
        dormant.get("status") != "DORMANT_VERIFIED"
        or dormant.get("roleLoginState") != "DISABLED"
        or dormant.get("credentialState") != "ABSENT"
    ):
        raise TransitionGateError("TRANSITION_GATE_DORMANCY_UNVERIFIED")
    return {
        "schemaVersion": "obsidian-b64-runtime-transition-gate.v1",
        "status": "TRANSITION_GATE_VERIFIED",
        "previousContainerId": previous_container_id,
        "containerId": dormant["container"]["containerId"],
        "imageId": expected_image_id,
        "serverVersionNum": expected_server_version_num,
        "systemIdentifier": expected_system_identifier,
        "rebindStatus": rebound["status"],
        "roleLoginState": "DISABLED",
        "credentialState": "ABSENT",
        "authorityIncreased": False,
        "credentialReadOrIssued": False,
        "customerRowsRead": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--container", default=PRODUCTION_CONTAINER)
    parser.add_argument("--expected-image-id", default=POSTGRES_17_11_IMAGE_ID)
    parser.add_argument(
        "--expected-volume", "--expected-volume-name",
        dest="expected_volume", default=PRODUCTION_VOLUME,
    )
    parser.add_argument("--expected-server-version-num", type=int, default=170011)
    parser.add_argument(
        "--expected-system-identifier", default=PRODUCTION_SYSTEM_IDENTIFIER
    )
    parser.add_argument("--allow-contract-container", action="store_true")
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = transition_gate_once(
            container_name=args.container,
            expected_image_id=args.expected_image_id,
            expected_volume_name=args.expected_volume,
            expected_server_version_num=args.expected_server_version_num,
            expected_system_identifier=args.expected_system_identifier,
            allow_contract_container=args.allow_contract_container,
            apply=args.apply,
        )
        code = 0
    except BaseException as exc:
        reason = (
            str(exc)
            if isinstance(exc, TransitionGateError)
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))
            else _safe_reason(exc)
        )
        result = {
            "schemaVersion": "obsidian-b64-runtime-transition-gate.v1",
            "status": "FAILED",
            "reason": reason,
            "authorityIncreased": False,
            "credentialReadOrIssued": False,
            "customerRowsRead": False,
        }
        code = 2
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
