#!/usr/bin/env python3
"""Truthful systemd shutdown wrapper: reconcile authority, then always stop PG."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

from b64_snapshot_reader_runtime_rebind import (
    POSTGRES_17_10_IMAGE_ID,
    POSTGRES_17_11_IMAGE_ID,
    PRODUCTION_CONTAINER,
    PRODUCTION_SYSTEM_IDENTIFIER,
    PRODUCTION_VOLUME,
    _safe_reason,
)
from b64_snapshot_reader_watchdog import watchdog_once


COMPOSE = Path("/opt/obsidian-exchange/deploy/postgres/compose.production.yml")
SUPPORTED_RUNTIMES = {
    POSTGRES_17_10_IMAGE_ID: 170010,
    POSTGRES_17_11_IMAGE_ID: 170011,
}


def _current_supported_runtime(container_name: str = PRODUCTION_CONTAINER) -> tuple[str, int]:
    inspected = subprocess.run(
        ["/usr/bin/docker", "inspect", container_name],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )
    if inspected.returncode != 0:
        raise RuntimeError("CONTAINER_INSPECT_FAILED")
    try:
        value = json.loads(inspected.stdout)[0]
        image_id = value["Image"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError("CONTAINER_INSPECTION_INVALID") from exc
    version = SUPPORTED_RUNTIMES.get(image_id)
    if version is None:
        raise RuntimeError("CURRENT_RUNTIME_NOT_ALLOWLISTED")
    return image_id, version


def _container_is_stopped(container_name: str = PRODUCTION_CONTAINER) -> bool:
    inspected = subprocess.run(
        ["/usr/bin/docker", "inspect", container_name],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=10,
        env={"PATH": "/usr/bin:/bin"},
    )
    if inspected.returncode != 0:
        return False
    try:
        state = json.loads(inspected.stdout)[0]["State"]
    except (IndexError, KeyError, TypeError, json.JSONDecodeError):
        return False
    return state.get("Running") is False and state.get("Pid") == 0


def shutdown(
    *,
    expected_image_id: str | None = None,
    expected_server_version_num: int | None = None,
    container_name: str = PRODUCTION_CONTAINER,
    expected_volume_name: str = PRODUCTION_VOLUME,
    expected_system_identifier: str = PRODUCTION_SYSTEM_IDENTIFIER,
    compose_path: Path = COMPOSE,
    compose_project: str = "obsidian-postgres",
    compose_service: str = "postgres",
    allow_contract_container: bool = False,
) -> tuple[dict, int]:
    if allow_contract_container:
        if (
            re.fullmatch(r"b64-hba-contract-[0-9]+", container_name) is None
            or re.fullmatch(r"b64[0-9a-f]{61}", expected_volume_name) is None
            or re.fullmatch(r"[0-9]{10,24}", expected_system_identifier) is None
            or compose_project != "obsidian-postgres-contract"
            or compose_service != "postgres-contract"
            or re.fullmatch(
                r"/tmp/b64-systemd-contract-[0-9]+/compose[.]yml",
                str(compose_path),
            ) is None
        ):
            raise RuntimeError("CONTRACT_SHUTDOWN_TARGET_INVALID")
    elif (
        container_name != PRODUCTION_CONTAINER
        or expected_volume_name != PRODUCTION_VOLUME
        or expected_system_identifier != PRODUCTION_SYSTEM_IDENTIFIER
        or compose_path != COMPOSE
        or compose_project != "obsidian-postgres"
        or compose_service != "postgres"
    ):
        raise RuntimeError("PRODUCTION_SHUTDOWN_TARGET_MISMATCH")
    reconciliation: dict
    reconcile_ok = False
    try:
        current_image_id, current_version = _current_supported_runtime(container_name)
        if expected_image_id is not None or expected_server_version_num is not None:
            if (
                expected_image_id is None
                or expected_server_version_num is None
                or SUPPORTED_RUNTIMES.get(expected_image_id)
                != expected_server_version_num
                or (expected_image_id, expected_server_version_num)
                != (current_image_id, current_version)
            ):
                raise RuntimeError("EXPECTED_RUNTIME_MISMATCH")
        else:
            expected_image_id = current_image_id
            expected_server_version_num = current_version
        reconciliation = watchdog_once(
            container_name=container_name,
            expected_image_id=expected_image_id,
            expected_volume_name=expected_volume_name,
            expected_server_version_num=expected_server_version_num,
            expected_system_identifier=expected_system_identifier,
            allow_contract_container=allow_contract_container,
            require_dormant=True,
        )
        reconcile_ok = (
            reconciliation.get("watchdogReady") is True
            and reconciliation.get("credentialState") == "ABSENT"
            and reconciliation.get("roleLoginState") == "DISABLED"
        )
    except BaseException as exc:
        reconciliation = {
            "status": "RECONCILE_UNCERTAIN",
            "reason": _safe_reason(exc),
        }

    stop_command = [
        "/usr/bin/docker",
        "compose",
            "--project-name",
        compose_project,
        "--file",
        str(compose_path),
        "stop",
        "--timeout",
        "120",
        compose_service,
    ]
    stop_timed_out = False
    try:
        stopped = subprocess.run(
            stop_command,
            check=False,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            timeout=140,
            env={"PATH": "/usr/bin:/bin"},
        )
        stop_exit_code: int | None = stopped.returncode
        stop_stderr_present = bool(stopped.stderr.strip())
    except subprocess.TimeoutExpired:
        stop_timed_out = True
        stop_exit_code = None
        stop_stderr_present = False
    except BaseException:
        stop_exit_code = None
        stop_stderr_present = False
    container_stopped = _container_is_stopped(container_name)
    stop_command_ok = stop_exit_code == 0 and not stop_timed_out
    result = {
        "schemaVersion": "obsidian-postgres-b64-bounded-shutdown.v1",
        "status": (
            "RECONCILED_AND_STOPPED"
            if reconcile_ok and container_stopped and stop_command_ok
            else "STOPPED_RECONCILE_UNCERTAIN"
            if container_stopped
            else "STOP_FAILED"
        ),
        "reconciliation": reconciliation,
        "containerStopExitCode": stop_exit_code,
        "containerStopTimedOut": stop_timed_out,
        "containerStopStderrPresent": stop_stderr_present,
        "containerStoppedPostverified": container_stopped,
        "credentialExposed": False,
        "customerRowsRead": False,
        "stopAttemptedRegardlessOfReconcile": True,
    }
    return result, 0 if reconcile_ok and container_stopped and stop_command_ok else 2


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expected-image-id")
    parser.add_argument("--expected-server-version-num", type=int)
    parser.add_argument("--container", default=PRODUCTION_CONTAINER)
    parser.add_argument("--expected-volume-name", default=PRODUCTION_VOLUME)
    parser.add_argument(
        "--expected-system-identifier", default=PRODUCTION_SYSTEM_IDENTIFIER
    )
    parser.add_argument("--compose-path", type=Path, default=COMPOSE)
    parser.add_argument("--compose-project", default="obsidian-postgres")
    parser.add_argument("--compose-service", default="postgres")
    parser.add_argument("--allow-contract-container", action="store_true")
    args = parser.parse_args()
    result, code = shutdown(
        expected_image_id=args.expected_image_id,
        expected_server_version_num=args.expected_server_version_num,
        container_name=args.container,
        expected_volume_name=args.expected_volume_name,
        expected_system_identifier=args.expected_system_identifier,
        compose_path=args.compose_path,
        compose_project=args.compose_project,
        compose_service=args.compose_service,
        allow_contract_container=args.allow_contract_container,
    )
    print(json.dumps(result, sort_keys=True))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
