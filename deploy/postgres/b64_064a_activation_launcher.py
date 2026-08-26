#!/usr/bin/env python3
"""Fixed-scope production supervisor for one signed 064A activation.

The launcher has no configurable command-line surface.  It requires one exact
root-owned launch request plus the already defined cleanup-recovery package and
request, verifies the signed activation boundary before constructing the
production executor, and forks exactly one worker into a new process group.
The parent enforces a wall-clock deadline and terminates the whole group; it
never retries.  Any non-terminal durable activation journal is intentionally
left for the separately deployed cleanup-only watchdog.
"""
from __future__ import annotations

import ctypes
import json
import os
import re
import signal
import stat
import sys
import time
from pathlib import Path
from typing import Any, Callable, Mapping

from psycopg.conninfo import make_conninfo

import b64_064a_activation_entrypoint as activation
import b64_064a_activation_executor as activation_executor
import b64_snapshot_reader_runtime as runtime
import b64_snapshot_reader_watchdog as watchdog


ROUTE = activation.ROUTE
UNIT_NAME = "obsidian-b64-064a-activation.service"
LAUNCH_REQUEST_NAME = "b64-064a-launch-request.v1.json"
ROLLBACK_INTENT_NAME = ".b64-064a-runtime-rollback.intent"
LAUNCH_REQUEST_SCHEMA = "b64-064a-production-launch-request.v1"
LAUNCH_ACTION = "EXECUTE_SIGNED_ACTIVATION_ONCE"
CREDENTIALS_DIRECTORY = Path(f"/run/credentials/{UNIT_NAME}")
OBSERVATION_CREDENTIAL_PATH = CREDENTIALS_DIRECTORY / "observation-env"
CHILD_WALL_SECONDS = 180.0
TERMINATION_GRACE_SECONDS = 3.0
FINAL_GROUP_WAIT_SECONDS = 2.0
POLL_SECONDS = 0.02
MAX_CHILD_RECEIPT_BYTES = 64 * 1024
PR_SET_PDEATHSIG = 1


class LauncherError(activation.ActivationError):
    """Closed launcher reason code safe for a secret-free receipt."""


def _closed_reason(exc: BaseException) -> str:
    reason = activation._reason(exc)
    if reason == "UNEXPECTED_ACTIVATION_FAILURE":
        return "LAUNCHER_UNEXPECTED_FAILURE"
    return reason


def _launcher_receipt(*, status: str, reason: str | None = None,
                      result: Mapping[str, Any] | None = None) -> dict[str, Any]:
    value: dict[str, Any] = {
        "schemaVersion": "b64-064a-production-launcher-receipt.v1",
        "route": ROUTE,
        "status": status,
        "automaticRetryAllowed": False,
        "processesRetried": 0,
        "actionAllowed": False,
    }
    if reason is not None:
        value["reason"] = reason
    if result is not None:
        value["activationResult"] = dict(result)
    return value


def _validate_launch_request(value: Mapping[str, Any]) -> dict[str, Any]:
    expected = {
        "schemaVersion", "route", "environment", "runNonce", "action",
        "operatorCommitOnly", "grantsAuthority", "automaticRetryAllowed",
        "expectedKeyringSha256", "planSha256", "decisionSha256",
        "recoveryManifestSha256",
    }
    if (not isinstance(value, Mapping) or set(value) != expected
            or value.get("schemaVersion") != LAUNCH_REQUEST_SCHEMA
            or value.get("route") != ROUTE
            or value.get("environment") != "PRODUCTION"
            or type(value.get("runNonce")) is not str
            or re.fullmatch(r"[A-Za-z0-9_-]{16,64}", value["runNonce"])
            is None
            or value.get("action") != LAUNCH_ACTION
            or value.get("operatorCommitOnly") is not True
            or value.get("grantsAuthority") is not False
            or value.get("automaticRetryAllowed") is not False):
        raise LauncherError("LAUNCH_REQUEST_INVALID")
    for name in (
        "expectedKeyringSha256", "planSha256", "decisionSha256",
        "recoveryManifestSha256",
    ):
        if (type(value.get(name)) is not str
                or re.fullmatch(r"[0-9a-f]{64}", value[name]) is None):
            raise LauncherError("LAUNCH_REQUEST_DIGEST_INVALID")
    return json.loads(activation._canonical(dict(value)))


def _load_launch_request() -> dict[str, Any]:
    parent_fd = watchdog._open_recovery_parent()
    if parent_fd is None:
        raise LauncherError("LAUNCH_REQUEST_PARENT_MISSING")
    try:
        entries = set(os.listdir(parent_fd))
        rollback_temps = {
            name for name in entries if re.fullmatch(
                re.escape(ROLLBACK_INTENT_NAME) + r"\.tmp-[0-9a-f]{24}",
                name,
            ) is not None
        }
        if ROLLBACK_INTENT_NAME in entries or rollback_temps:
            raise LauncherError("LAUNCH_RUNTIME_ROLLBACK_IN_PROGRESS")
        raw = watchdog._read_bound_file(
            parent_fd, LAUNCH_REQUEST_NAME, mode=0o400,
            maximum=64 * 1024, missing_ok=True,
        )
        if raw is None:
            raise LauncherError("LAUNCH_REQUEST_MISSING")
        try:
            value = watchdog._decode_object(raw, "LAUNCH_REQUEST_INVALID")
        except watchdog.WatchdogError as exc:
            raise LauncherError("LAUNCH_REQUEST_INVALID") from exc
        return _validate_launch_request(value)
    except watchdog.WatchdogError as exc:
        raise LauncherError("LAUNCH_REQUEST_UNSAFE") from exc
    finally:
        os.close(parent_fd)


def _load_committed_package(
    launch_request: Mapping[str, Any] | None = None,
) -> tuple[dict[str, Any], Any]:
    if launch_request is None:
        launch_request = _load_launch_request()
    else:
        launch_request = _validate_launch_request(launch_request)
    try:
        package = watchdog._load_recovery_package()
    except watchdog.WatchdogError as exc:
        raise LauncherError("LAUNCH_RECOVERY_PACKAGE_INVALID") from exc
    if package is None:
        raise LauncherError("LAUNCH_RECOVERY_PACKAGE_MISSING")
    if package.get("stagedWithoutRequest") is True:
        raise LauncherError("LAUNCH_RECOVERY_REQUEST_MISSING")
    request = package.get("request")
    if not isinstance(request, Mapping):
        raise LauncherError("LAUNCH_RECOVERY_REQUEST_INVALID")
    exact_fields = {
        "runNonce": "runNonce",
        "expectedKeyringSha256": "expectedKeyringSha256",
        "planSha256": "planSha256",
        "decisionSha256": "decisionSha256",
        "recoveryManifestSha256": "manifestSha256",
    }
    if any(
        launch_request[launch_name] != request.get(recovery_name)
        for launch_name, recovery_name in exact_fields.items()
    ):
        raise LauncherError("LAUNCH_RECOVERY_BINDING_MISMATCH")
    keyring_raw = package.get("keyring.json")
    decision_raw = package.get("decision.json")
    plan_raw = package.get("activation-plan.json")
    if not all(type(raw) is bytes for raw in (
        keyring_raw, decision_raw, plan_raw,
    )):
        raise LauncherError("LAUNCH_PACKAGE_ARTIFACT_INVALID")
    try:
        now_epoch, _clock_evidence = activation.supervisor._trusted_now_epoch()
        verified = activation.verify_activation_decision(
            keyring_raw=keyring_raw, decision_raw=decision_raw,
            activation_plan_raw=plan_raw,
            expected_keyring_sha256=launch_request[
                "expectedKeyringSha256"
            ],
            expected_environment="PRODUCTION", now_epoch=now_epoch,
        )
    except activation.supervisor.SupervisorError as exc:
        raise LauncherError(str(exc)) from exc
    if (verified.run_nonce != launch_request["runNonce"]
            or verified.keyring_sha256
            != launch_request["expectedKeyringSha256"]
            or verified.plan_sha256 != launch_request["planSha256"]
            or verified.decision_sha256
            != launch_request["decisionSha256"]):
        raise LauncherError("LAUNCH_VERIFIED_BINDING_MISMATCH")
    return package, verified


def _safe_observation_credential(path: Path) -> tuple[bytearray, bytes]:
    descriptor = -1
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0 or metadata.st_gid != 0
                or stat.S_IMODE(metadata.st_mode) & 0o077
                or metadata.st_nlink != 1
                or not 128 <= metadata.st_size <= 2048):
            raise LauncherError("LAUNCH_OBSERVATION_CREDENTIAL_UNSAFE")
        raw = bytearray()
        while len(raw) < metadata.st_size:
            chunk = os.read(descriptor, metadata.st_size - len(raw))
            if not chunk:
                raise LauncherError(
                    "LAUNCH_OBSERVATION_CREDENTIAL_SHORT_READ"
                )
            raw.extend(chunk)
        if os.read(descriptor, 1):
            raise LauncherError("LAUNCH_OBSERVATION_CREDENTIAL_GREW")
        after = os.fstat(descriptor)
        if ((after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
             after.st_ctime_ns, after.st_mode, after.st_uid, after.st_gid,
             after.st_nlink)
                != (metadata.st_dev, metadata.st_ino, metadata.st_size,
                    metadata.st_mtime_ns, metadata.st_ctime_ns,
                    metadata.st_mode, metadata.st_uid, metadata.st_gid,
                    metadata.st_nlink)):
            raise LauncherError("LAUNCH_OBSERVATION_CREDENTIAL_CHANGED")
    except OSError as exc:
        raise LauncherError("LAUNCH_OBSERVATION_CREDENTIAL_UNSAFE") from exc
    finally:
        if descriptor >= 0:
            os.close(descriptor)
    matched = re.fullmatch(
        rb"EXCHANGE_DB_CONNECTION=pgsql\n"
        rb"EXCHANGE_DATABASE_URL=postgresql://"
        rb"(obsidian_readonly):([A-Za-z0-9_-]{32,255})"
        rb"@127\.0\.0\.1:5432/obsidian_exchange\n"
        rb"EXCHANGE_DB_SSLMODE=disable\n?",
        raw,
    )
    if matched is None:
        for index in range(len(raw)):
            raw[index] = 0
        raise LauncherError("LAUNCH_OBSERVATION_CREDENTIAL_INVALID")
    principal = bytes(matched.group(1))
    password = bytearray(matched.group(2))
    for index in range(len(raw)):
        raw[index] = 0
    return password, principal


def _production_connections(
    *, container_pid: int,
    credential_path: Path = OBSERVATION_CREDENTIAL_PATH,
) -> tuple[int, str, str]:
    if type(container_pid) is not int or container_pid <= 1:
        raise LauncherError("LAUNCH_CONTAINER_PID_INVALID")
    password, principal = _safe_observation_credential(credential_path)
    passline = bytearray(b"127.0.0.1:5432:obsidian_exchange:")
    passline.extend(principal)
    passline.extend(b":")
    passline.extend(password)
    passline.extend(b"\n")
    for index in range(len(password)):
        password[index] = 0
    try:
        passfile_fd = runtime._sealed_pgpass_memfd(
            bytes(passline), "obsidian-b64-064a-launcher-pgpass",
        )
    finally:
        for index in range(len(passline)):
            passline[index] = 0
    observation_dsn = make_conninfo(
        host="127.0.0.1", port=5432, dbname=runtime.DATABASE,
        user=principal.decode("ascii"),
        passfile=f"/proc/self/fd/{passfile_fd}",
        connect_timeout=5, sslmode="disable",
        # obsidian_readonly has default_transaction_read_only=on.  libpq's
        # read-write probe rejects that deliberately read-only session before
        # the activation executor can attest the dormant target.
        target_session_attrs="read-only",
        application_name="obsidian-b64-064a-activation-launcher",
    )
    admin_dsn = make_conninfo(
        host=f"/proc/{container_pid}/root/var/run/postgresql",
        port=5432, dbname=runtime.DATABASE, user="postgres",
        connect_timeout=5, sslmode="disable",
        target_session_attrs="read-write",
        application_name="obsidian-b64-064a-activation-launcher-admin",
    )
    return passfile_fd, observation_dsn, admin_dsn


def _reject_ambient_authority() -> None:
    if sys.argv != [sys.argv[0]]:
        raise LauncherError("LAUNCHER_ARGUMENTS_FORBIDDEN")
    if any(name.startswith("PG") for name in os.environ):
        raise LauncherError("LAUNCHER_AMBIENT_LIBPQ_ENVIRONMENT_FORBIDDEN")
    credentials = os.environ.get("CREDENTIALS_DIRECTORY")
    if credentials is not None and credentials != str(CREDENTIALS_DIRECTORY):
        raise LauncherError("LAUNCHER_CREDENTIAL_DIRECTORY_MISMATCH")


def _execute_production_once() -> dict[str, Any]:
    _reject_ambient_authority()
    launch_request = _load_launch_request()
    lease = activation.claim_precommitted_production_execution(
        run_nonce=launch_request["runNonce"],
        plan_sha256=launch_request["planSha256"],
        decision_sha256=launch_request["decisionSha256"],
    )
    passfile_fd = -1
    try:
        # The committer's durable CLAIMED journal is consumed to RUNNING and
        # both serialization locks are held before package/time/target or
        # credential work.  Every failure below is therefore cleanup-only and
        # a later manual start cannot replay the signed launch request.
        package, verified = _load_committed_package(launch_request)
        observed = activation_executor._inspect_container(
            activation.PRODUCTION_CONTAINER
        )
        if observed is None:
            raise LauncherError("LAUNCH_PRODUCTION_CONTAINER_MISSING")
        try:
            container_id = observed["Id"].removeprefix("sha256:")
            image_id = observed["Image"]
            running = observed["State"]["Running"]
            container_pid = observed["State"]["Pid"]
        except (KeyError, TypeError, AttributeError) as exc:
            raise LauncherError("LAUNCH_PRODUCTION_CONTAINER_INVALID") from exc
        if (container_id != verified.target.get("containerId")
                or image_id != activation.PRODUCTION_IMAGE_ID
                or running is not True
                or type(container_pid) is not int or container_pid <= 1):
            raise LauncherError("LAUNCH_PRODUCTION_TARGET_MISMATCH")
        passfile_fd, observation_dsn, admin_dsn = _production_connections(
            container_pid=container_pid
        )
        dormant = activation_executor.BoundRecoveryExecutor(
            container=activation.PRODUCTION_CONTAINER,
            container_id=container_id, image_id=image_id,
            system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
            workspace_parent=activation.PRODUCTION_WORKSPACE_ROOT,
            proxy_parent=activation.PRODUCTION_PROXY_ROOT,
            resource_journal_root=(
                activation.PRODUCTION_RESOURCE_JOURNAL_ROOT
            ),
        )
        executor = activation_executor.BoundActivationExecutor(
            production_contact=True, observation_dsn=observation_dsn,
            admin_dsn=admin_dsn, container=activation.PRODUCTION_CONTAINER,
            container_id=container_id, image_id=image_id,
            system_identifier=activation.PRODUCTION_SYSTEM_IDENTIFIER,
            workspace_parent=activation.PRODUCTION_WORKSPACE_ROOT,
            proxy_parent=activation.PRODUCTION_PROXY_ROOT,
            resource_journal_root=(
                activation.PRODUCTION_RESOURCE_JOURNAL_ROOT
            ),
        )
        now_epoch, _clock_evidence = activation.supervisor._trusted_now_epoch()
        result = activation.run_once(
            keyring_raw=package["keyring.json"],
            decision_raw=package["decision.json"],
            activation_plan_raw=package["activation-plan.json"],
            expected_keyring_sha256=verified.keyring_sha256,
            expected_environment="PRODUCTION", now_epoch=now_epoch,
            journal_root=activation.PRODUCTION_JOURNAL_ROOT,
            executor=executor, reconcile=dormant.attest_dormant,
            verify_dormant=dormant.attest_dormant,
            production_lease=lease,
        )
    finally:
        if passfile_fd >= 0:
            os.close(passfile_fd)
        lease.close()
    if (result.get("status") != "ACTIVATION_COMPLETED_DORMANT_VERIFIED"
            or result.get("journalState") != "CLOSED"
            or result.get("automaticRetryAllowed") is not False
            or result.get("actionAllowed") is not False):
        raise LauncherError("LAUNCH_ACTIVATION_RESULT_INVALID")
    return result


def _write_child_receipt(descriptor: int, receipt: Mapping[str, Any]) -> None:
    raw = activation._canonical(dict(receipt)) + b"\n"
    if len(raw) > MAX_CHILD_RECEIPT_BYTES:
        raw = activation._canonical(_launcher_receipt(
            status="NO_GO", reason="LAUNCHER_RECEIPT_TOO_LARGE",
        )) + b"\n"
    activation._write_all(descriptor, raw)


def _arm_parent_death_signal(parent_pid: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(PR_SET_PDEATHSIG, signal.SIGKILL, 0, 0, 0) != 0:
        raise LauncherError("LAUNCHER_PARENT_DEATH_SIGNAL_FAILED")
    if os.getppid() != parent_pid:
        raise LauncherError("LAUNCHER_PARENT_CHANGED")


def _group_exists(group_id: int) -> bool:
    try:
        os.killpg(group_id, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError as exc:
        raise LauncherError("LAUNCHER_PROCESS_GROUP_UNOWNED") from exc


def _wait_child(child_pid: int) -> tuple[bool, int | None]:
    try:
        waited, status = os.waitpid(child_pid, os.WNOHANG)
    except ChildProcessError:
        return True, None
    return waited == child_pid, status if waited == child_pid else None


def _terminate_unready_child(
    child_pid: int, *, monotonic: Callable[[], float], hard_deadline: float,
) -> int | None:
    for target_group in (True, False):
        try:
            if target_group:
                os.killpg(child_pid, signal.SIGTERM)
            else:
                os.kill(child_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    while monotonic() < hard_deadline:
        done, status = _wait_child(child_pid)
        if done:
            return status
        time.sleep(POLL_SECONDS)
    for target_group in (True, False):
        try:
            if target_group:
                os.killpg(child_pid, signal.SIGKILL)
            else:
                os.kill(child_pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
    try:
        return os.waitpid(child_pid, 0)[1]
    except ChildProcessError:
        return None


def _terminate_process_group(
    child_pid: int, *, hard_deadline: float,
    monotonic: Callable[[], float] = time.monotonic,
    final_wait_seconds: float = FINAL_GROUP_WAIT_SECONDS,
) -> int | None:
    status: int | None = None
    try:
        os.killpg(child_pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    while monotonic() < hard_deadline:
        done, observed = _wait_child(child_pid)
        if done and status is None:
            status = observed
        if not _group_exists(child_pid):
            return status
        time.sleep(POLL_SECONDS)
    try:
        os.killpg(child_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    kill_deadline = monotonic() + final_wait_seconds
    while monotonic() < kill_deadline:
        done, observed = _wait_child(child_pid)
        if done and status is None:
            status = observed
        if not _group_exists(child_pid):
            return status
        time.sleep(POLL_SECONDS)
    done, observed = _wait_child(child_pid)
    if done and status is None:
        status = observed
    if _group_exists(child_pid):
        raise LauncherError("LAUNCHER_PROCESS_GROUP_SURVIVED_KILL")
    return status


def supervise_once(
    worker: Callable[[], Mapping[str, Any]], *,
    wall_seconds: float = CHILD_WALL_SECONDS,
    monotonic: Callable[[], float] = time.monotonic,
) -> tuple[int, dict[str, Any]]:
    if (type(wall_seconds) not in {int, float}
            or not 0.05 <= wall_seconds <= CHILD_WALL_SECONDS):
        raise LauncherError("LAUNCHER_WALL_TIMEOUT_INVALID")
    handled_signals = (signal.SIGTERM, signal.SIGINT, signal.SIGHUP)
    previous_mask = signal.pthread_sigmask(
        signal.SIG_BLOCK, handled_signals,
    )
    read_fd, write_fd = os.pipe2(os.O_CLOEXEC)
    ready_read_fd, ready_write_fd = os.pipe2(os.O_CLOEXEC)
    started = monotonic()
    launcher_parent_pid = os.getpid()
    try:
        child_pid = os.fork()
    except BaseException:
        for descriptor in (
            read_fd, write_fd, ready_read_fd, ready_write_fd,
        ):
            os.close(descriptor)
        signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
        raise
    if child_pid == 0:
        os.close(read_fd)
        os.close(ready_read_fd)
        exit_code = 3
        try:
            _arm_parent_death_signal(launcher_parent_pid)
            os.setsid()
            for signum in handled_signals:
                signal.signal(signum, signal.SIG_DFL)
            signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
            activation._write_all(ready_write_fd, b"R")
            os.close(ready_write_fd)
            ready_write_fd = -1
            result = dict(worker())
            receipt = _launcher_receipt(
                status="ACTIVATION_COMPLETED_DORMANT_VERIFIED",
                result=result,
            )
            exit_code = 0
        except BaseException as exc:
            receipt = _launcher_receipt(
                status="NO_GO", reason=_closed_reason(exc),
            )
        try:
            _write_child_receipt(write_fd, receipt)
        except BaseException:
            exit_code = 3
        finally:
            if ready_write_fd >= 0:
                os.close(ready_write_fd)
            os.close(write_fd)
        os._exit(exit_code)
    os.close(write_fd)
    os.close(ready_write_fd)
    os.set_blocking(ready_read_fd, False)
    hard_deadline = started + wall_seconds
    term_deadline = hard_deadline - min(
        TERMINATION_GRACE_SECONDS, wall_seconds / 2,
    )
    interrupted_signal: int | None = None
    child_status: int | None = None

    def interrupted(signum: int, _frame: Any) -> None:
        nonlocal interrupted_signal
        interrupted_signal = signum

    previous_handlers = {
        signum: signal.signal(signum, interrupted)
        for signum in handled_signals
    }
    signal.pthread_sigmask(signal.SIG_SETMASK, previous_mask)
    timed_out = False
    ready = False
    try:
        readiness_deadline = min(term_deadline, started + 2.0)
        while not ready:
            try:
                marker = os.read(ready_read_fd, 1)
            except BlockingIOError:
                marker = None
            if marker == b"R":
                ready = True
                break
            done, status = _wait_child(child_pid)
            if done:
                child_status = status
                break
            if interrupted_signal is not None:
                break
            if monotonic() >= readiness_deadline:
                timed_out = True
                break
            time.sleep(POLL_SECONDS)
        os.close(ready_read_fd)
        ready_read_fd = -1
        while True:
            if not ready or child_status is not None:
                break
            done, status = _wait_child(child_pid)
            if done:
                child_status = status
                break
            if interrupted_signal is not None:
                break
            if monotonic() >= term_deadline:
                timed_out = True
                break
            time.sleep(POLL_SECONDS)
        if timed_out or interrupted_signal is not None:
            termination_deadline = (
                hard_deadline if timed_out else min(
                    hard_deadline,
                    monotonic() + TERMINATION_GRACE_SECONDS,
                )
            )
            if ready:
                child_status = _terminate_process_group(
                    child_pid, hard_deadline=termination_deadline,
                    monotonic=monotonic,
                )
            else:
                child_status = _terminate_unready_child(
                    child_pid, hard_deadline=termination_deadline,
                    monotonic=monotonic,
                )
    finally:
        if ready_read_fd >= 0:
            os.close(ready_read_fd)
        for signum, handler in previous_handlers.items():
            signal.signal(signum, handler)
    residual_group = _group_exists(child_pid)
    if residual_group:
        _terminate_process_group(
            child_pid,
            hard_deadline=min(
                hard_deadline,
                monotonic() + TERMINATION_GRACE_SECONDS,
            ),
            monotonic=monotonic,
        )
    raw = bytearray()
    try:
        while len(raw) <= MAX_CHILD_RECEIPT_BYTES:
            chunk = os.read(
                read_fd, min(4096, MAX_CHILD_RECEIPT_BYTES + 1 - len(raw))
            )
            if not chunk:
                break
            raw.extend(chunk)
    finally:
        os.close(read_fd)
    if timed_out:
        return 3, _launcher_receipt(
            status="NO_GO",
            reason="LAUNCHER_HARD_WALL_TIMEOUT_PROCESS_GROUP_TERMINATED",
        )
    if interrupted_signal is not None:
        return 3, _launcher_receipt(
            status="NO_GO",
            reason="LAUNCHER_SIGNAL_PROCESS_GROUP_TERMINATED",
        )
    if residual_group:
        return 3, _launcher_receipt(
            status="NO_GO",
            reason="LAUNCHER_RESIDUAL_PROCESS_GROUP_TERMINATED",
        )
    if len(raw) > MAX_CHILD_RECEIPT_BYTES or not raw.endswith(b"\n"):
        return 3, _launcher_receipt(
            status="NO_GO", reason="LAUNCHER_CHILD_RECEIPT_INVALID",
        )
    try:
        receipt = watchdog._decode_object(
            bytes(raw), "LAUNCHER_CHILD_RECEIPT_INVALID"
        )
    except watchdog.WatchdogError:
        return 3, _launcher_receipt(
            status="NO_GO", reason="LAUNCHER_CHILD_RECEIPT_INVALID",
        )
    exited_ok = (
        child_status is not None and os.WIFEXITED(child_status)
        and os.WEXITSTATUS(child_status) == 0
    )
    if exited_ok and receipt.get("status") \
            == "ACTIVATION_COMPLETED_DORMANT_VERIFIED":
        return 0, receipt
    return 3, receipt


def main() -> int:
    os.umask(0o077)
    try:
        code, receipt = supervise_once(_execute_production_once)
    except BaseException as exc:
        code = 3
        receipt = _launcher_receipt(
            status="NO_GO", reason=_closed_reason(exc),
        )
    print(json.dumps(receipt, sort_keys=True, separators=(",", ":")))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
