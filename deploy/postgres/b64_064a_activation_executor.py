#!/usr/bin/env python3
"""Artifact-bound 064A activation executor with no activation CLI.

The same implementation is rehearsed against an allowlisted disposable
PostgreSQL container.  Production construction is inert until `run_once()` has
verified a fresh activation-v2 package, durably claimed its journal, and passed
the sealed `VerifiedActivation` capability into `execute()`.

The only command-line mode is an internal Unix-to-127.0.0.1 proxy helper.  It
has no credential, package, journal, Docker or activation interface.  The
digest-pinned pg_dump container remains network-none and can reach only that
single proxy socket.
"""
from __future__ import annotations

import argparse
import ctypes
import fcntl
import hashlib
import json
import os
import re
import resource
import selectors
import signal
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Mapping

import psycopg
from psycopg import sql
from psycopg.conninfo import make_conninfo

import b64_064a_activation_entrypoint as activation
import b64_064a_hardened_refresh as refresh
import b64_snapshot_reader_runtime as runtime
from verify_b64_snapshot_reader import inspect


ROOT = Path(__file__).resolve().parents[2]
POSTGRES = Path(__file__).resolve().parent
DOCKER = "/usr/bin/docker"
NSENTER = "/usr/bin/nsenter"
PYTHON = "/usr/bin/python3"
MINIMAL_ENV = {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}
PROXY_SOCKET_NAME = ".s.PGSQL.5432"
MAX_STDERR_BYTES = 64 * 1024
DOCKER_ROUTE_LABEL = "e0-e0.3-b5.3-064a"


class ExecutorError(
    activation.ActivationError, refresh.HardenedRefreshError,
):
    """Closed reason code safe for activation receipts."""


def _run(command: list[str], **kwargs: Any) -> subprocess.CompletedProcess[Any]:
    if not command or command[0] != DOCKER:
        raise ExecutorError("EXECUTOR_COMMAND_NOT_ALLOWLISTED")
    kwargs.setdefault("timeout", 8)
    return subprocess.run(
        command, check=False, capture_output=True, env=MINIMAL_ENV, **kwargs,
    )


def _inspect_container(reference: str) -> dict[str, Any] | None:
    if re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", reference) is None:
        raise ExecutorError("CONTAINER_REFERENCE_INVALID")
    template = (
        '{"Id":{{json .Id}},"Name":{{json .Name}},'
        '"Image":{{json .Image}},"State":{"Pid":{{json .State.Pid}},'
        '"Running":{{json .State.Running}}},'
        '"Labels":{{json .Config.Labels}}}'
    )
    observed = _run(
        [DOCKER, "inspect", f"--format={template}", reference], text=True,
    )
    if observed.returncode != 0:
        missing = (
            f"Error: No such object: {reference}\n",
            f"error: no such object: {reference}\n",
            f"Error response from daemon: No such container: {reference}\n",
        )
        if observed.stderr in missing and observed.stdout in {"", "\n"}:
            return None
        raise ExecutorError("CONTAINER_INSPECTION_UNAVAILABLE")
    try:
        values = json.loads(observed.stdout)
    except json.JSONDecodeError as exc:
        raise ExecutorError("CONTAINER_INSPECTION_INVALID") from exc
    if not isinstance(values, dict):
        raise ExecutorError("CONTAINER_INSPECTION_AMBIGUOUS")
    return values


def _container_id(value: Any) -> str:
    if type(value) is not str:
        raise ExecutorError("INVALID_EXECUTOR_CONTAINER_ID")
    candidate = value.removeprefix("sha256:")
    if re.fullmatch(r"[0-9a-f]{64}", candidate) is None:
        raise ExecutorError("INVALID_EXECUTOR_CONTAINER_ID")
    return candidate


def _safe_parent(path: Path, code: str) -> None:
    if not path.is_absolute():
        raise ExecutorError(code)
    try:
        fd = os.open(
            path, os.O_RDONLY | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0),
        )
        metadata = os.fstat(fd)
    except OSError as exc:
        raise ExecutorError(code) from exc
    finally:
        if "fd" in locals():
            os.close(fd)
    if (metadata.st_uid != os.geteuid()
            or stat.S_IMODE(metadata.st_mode) != 0o700):
        raise ExecutorError(code)


def _write_manifest(
    directory_fd: int, name: str, value: Any,
) -> None:
    descriptor = os.open(
        name, os.O_WRONLY | os.O_TRUNC | getattr(os, "O_NOFOLLOW", 0),
        dir_fd=directory_fd,
    )
    raw = activation._canonical(value) + b"\n"
    try:
        offset = 0
        while offset < len(raw):
            written = os.write(descriptor, raw[offset:])
            if written <= 0:
                raise ExecutorError("MANIFEST_SHORT_WRITE")
            offset += written
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _open_bound_artifact(path: Path, expected_sha256: str) -> tuple[int, bytes]:
    descriptor = -1
    try:
        descriptor = os.open(
            path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        metadata = os.fstat(descriptor)
        if (not stat.S_ISREG(metadata.st_mode)
                or metadata.st_uid != 0
                or stat.S_IMODE(metadata.st_mode) & 0o022
                or metadata.st_nlink != 1
                or not 1 <= metadata.st_size <= 2 * 1024 * 1024):
            raise ExecutorError("EXECUTOR_ARTIFACT_UNSAFE")
        raw = b""
        while len(raw) < metadata.st_size:
            chunk = os.read(descriptor, metadata.st_size - len(raw))
            if not chunk:
                raise ExecutorError("EXECUTOR_ARTIFACT_SHORT_READ")
            raw += chunk
    except OSError as exc:
        if descriptor >= 0:
            os.close(descriptor)
        raise ExecutorError("EXECUTOR_ARTIFACT_UNSAFE") from exc
    except BaseException:
        if descriptor >= 0:
            os.close(descriptor)
        raise
    if (type(expected_sha256) is not str
            or hashlib.sha256(raw).hexdigest() != expected_sha256):
        os.close(descriptor)
        raise ExecutorError("EXECUTOR_ARTIFACT_DRIFT")
    os.lseek(descriptor, 0, os.SEEK_SET)
    return descriptor, raw


def _read_bound_artifact(path: Path, expected_sha256: str) -> bytes:
    descriptor, raw = _open_bound_artifact(path, expected_sha256)
    os.close(descriptor)
    return raw


def _execute_bound(conn: Any, source: str, database: str) -> None:
    conn.execute(sql.SQL(
        "SET obsidian.snapshot_reader_expected_database = {}"
    ).format(sql.Literal(database)))
    conn.execute("SET obsidian.snapshot_reader_require_absent = 'on'")
    conn.execute(sql.SQL(
        "SET obsidian.snapshot_reader_deployment_nonce = {}"
    ).format(sql.Literal("1234567890abcdef1234567890abcdef")))
    conn.execute(source)


def _proxy_name(run_nonce: str) -> str:
    return "b64-064a-proxy-" + hashlib.sha256(
        run_nonce.encode("ascii")
    ).hexdigest()[:20]


def _restore_name(run_nonce: str) -> str:
    return "b64-064a-restore-" + hashlib.sha256(
        run_nonce.encode("ascii")
    ).hexdigest()[:20]


def _path_entry_absent(path: Path) -> bool:
    try:
        path.lstat()
    except FileNotFoundError:
        return True
    except OSError as exc:
        raise ExecutorError("RESOURCE_ABSENCE_CHECK_FAILED") from exc
    return False


def _dump_name(run_nonce: str) -> str:
    return "b64-064a-dump-" + hashlib.sha256(
        run_nonce.encode("ascii")
    ).hexdigest()[:20]


class ExecutorResourceJournal:
    SCHEMA = "b64-064a-executor-resource-journal.v1"

    def __init__(
        self, *, root: Path, run_nonce: str, environment: str,
        target: Mapping[str, Any], plan_sha256: str,
        decision_sha256: str, derived_plan_sha256: str,
    ) -> None:
        _safe_parent(root, "EXECUTOR_JOURNAL_ROOT_UNSAFE")
        self.root = root
        self.run_nonce = run_nonce
        self.path = root / f"{run_nonce}.resources.json"
        self.initial = {
            "schemaVersion": self.SCHEMA,
            "route": activation.ROUTE,
            "runNonce": run_nonce,
            "environment": environment,
            "target": dict(target),
            "planSha256": plan_sha256,
            "decisionSha256": decision_sha256,
            "derivedExecutionPlanSha256": derived_plan_sha256,
            "state": "PREPARED",
            "workspaceName": f"b64-064a-{run_nonce}",
            "workspaceDev": None,
            "workspaceIno": None,
            "proxyName": _proxy_name(run_nonce),
            "dumpName": _dump_name(run_nonce),
            "restoreName": _restore_name(run_nonce),
            "proxyPid": None,
            "proxyStartTime": None,
            "dumpContainerId": None,
            "restoreContainerId": None,
            "credentialIssued": False,
            "credentialReconciled": False,
            "workspaceAbsent": False,
            "proxyAbsent": False,
            "dumpAbsent": False,
            "restoreAbsent": False,
        }

    def _open_root(self) -> int:
        try:
            descriptor = os.open(
                self.root, os.O_RDONLY | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            metadata = os.fstat(descriptor)
        except OSError as exc:
            raise ExecutorError("EXECUTOR_JOURNAL_ROOT_UNSAFE") from exc
        if (metadata.st_uid != os.geteuid()
                or stat.S_IMODE(metadata.st_mode) != 0o700):
            os.close(descriptor)
            raise ExecutorError("EXECUTOR_JOURNAL_ROOT_UNSAFE")
        return descriptor

    def _read_at(self, directory_fd: int) -> dict[str, Any]:
        descriptor = -1
        try:
            descriptor = os.open(
                self.path.name,
                os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                dir_fd=directory_fd,
            )
            metadata = os.fstat(descriptor)
            if (not stat.S_ISREG(metadata.st_mode)
                    or metadata.st_uid != os.geteuid()
                    or stat.S_IMODE(metadata.st_mode) != 0o600
                    or metadata.st_nlink != 1
                    or not 1 <= metadata.st_size <= 64 * 1024):
                raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_UNSAFE")
            raw = b""
            while len(raw) < metadata.st_size:
                chunk = os.read(descriptor, metadata.st_size - len(raw))
                if not chunk:
                    raise ExecutorError(
                        "EXECUTOR_RESOURCE_JOURNAL_SHORT_READ"
                    )
                raw += chunk
            if os.read(descriptor, 1):
                raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_GREW")
            value = json.loads(raw)
        except (OSError, json.JSONDecodeError) as exc:
            raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_INVALID") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if (not isinstance(value, dict)
                or set(value) != set(self.initial)
                or value.get("schemaVersion") != self.SCHEMA
                or value.get("route") != activation.ROUTE
                or value.get("runNonce") != self.run_nonce
                or value.get("environment") != self.initial["environment"]
                or value.get("target") != self.initial["target"]
                or value.get("planSha256") != self.initial["planSha256"]
                or value.get("decisionSha256")
                != self.initial["decisionSha256"]
                or value.get("derivedExecutionPlanSha256")
                != self.initial["derivedExecutionPlanSha256"]
                or value.get("workspaceName") != self.initial["workspaceName"]
                or value.get("proxyName") != self.initial["proxyName"]
                or value.get("dumpName") != self.initial["dumpName"]
                or value.get("restoreName") != self.initial["restoreName"]
                or value.get("state") not in {
                    "PREPARED", "RUNNING", "HOLD", "CLOSED",
                    "RECONCILED_HOLD",
                }):
            raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_INVALID")
        return value

    @staticmethod
    def _validate_transition(
        current: Mapping[str, Any], value: Mapping[str, Any],
    ) -> None:
        allowed = {
            "PREPARED": {"RUNNING", "HOLD"},
            "RUNNING": {"RUNNING", "HOLD", "CLOSED"},
            "HOLD": {"HOLD", "RECONCILED_HOLD"},
            "CLOSED": set(),
            "RECONCILED_HOLD": set(),
        }
        if value["state"] not in allowed[current["state"]]:
            raise ExecutorError("EXECUTOR_RESOURCE_STATE_CONFLICT")
        for name in (
            "credentialIssued", "credentialReconciled", "workspaceAbsent",
            "proxyAbsent", "dumpAbsent", "restoreAbsent",
        ):
            if current[name] is True and value[name] is not True:
                raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_REGRESSION")
        for name in (
            "proxyPid", "proxyStartTime", "dumpContainerId",
            "restoreContainerId",
        ):
            if current[name] is not None and value[name] != current[name]:
                raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_REGRESSION")
        if ((value["proxyPid"] is None) !=
                (value["proxyStartTime"] is None)):
            raise ExecutorError("EXECUTOR_PROXY_JOURNAL_INCOMPLETE")
        if ((value["workspaceDev"] is None) !=
                (value["workspaceIno"] is None)):
            raise ExecutorError("EXECUTOR_WORKSPACE_JOURNAL_INCOMPLETE")
        for name in ("workspaceDev", "workspaceIno"):
            if (value[name] is not None
                    and (type(value[name]) is not int or value[name] <= 0)):
                raise ExecutorError("EXECUTOR_WORKSPACE_JOURNAL_INVALID")
            if current[name] is not None and value[name] != current[name]:
                raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_REGRESSION")

    def create(self) -> None:
        raw = activation._canonical(self.initial) + b"\n"
        directory_fd = self._open_root()
        try:
            descriptor = os.open(
                self.path.name,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0),
                0o600, dir_fd=directory_fd,
            )
            try:
                activation._write_all(descriptor, raw)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.fsync(directory_fd)
        except FileExistsError as exc:
            raise ExecutorError(
                "EXECUTOR_RESOURCE_JOURNAL_REPLAY"
            ) from exc
        finally:
            os.close(directory_fd)

    def update(self, **changes: Any) -> dict[str, Any]:
        if not set(changes) <= set(self.initial):
            raise ExecutorError("EXECUTOR_RESOURCE_JOURNAL_UPDATE_INVALID")
        directory_fd = self._open_root()
        temporary = (
            f".{self.path.name}.{os.getpid()}.{time.monotonic_ns()}.tmp"
        )
        try:
            current = self._read_at(directory_fd)
            value = {**current, **changes}
            self._validate_transition(current, value)
            raw = activation._canonical(value) + b"\n"
            descriptor = os.open(
                temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0), 0o600,
                dir_fd=directory_fd,
            )
            try:
                activation._write_all(descriptor, raw)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(
                temporary, self.path.name,
                src_dir_fd=directory_fd, dst_dir_fd=directory_fd,
            )
            os.fsync(directory_fd)
        finally:
            try:
                os.unlink(temporary, dir_fd=directory_fd)
            except OSError:
                pass
            os.close(directory_fd)
        return value

    def inspect(self) -> dict[str, Any]:
        directory_fd = self._open_root()
        try:
            return self._read_at(directory_fd)
        finally:
            os.close(directory_fd)

    def inspect_optional(self) -> dict[str, Any] | None:
        directory_fd = self._open_root()
        try:
            try:
                os.stat(
                    self.path.name, dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return None
            return self._read_at(directory_fd)
        finally:
            os.close(directory_fd)


def _proxy_helper(
    socket_path: Path, lifetime_seconds: int, registration_fd: int,
) -> int:
    """Relay one Unix client to the exact PostgreSQL loopback endpoint."""
    if (not socket_path.is_absolute()
            or socket_path.name != PROXY_SOCKET_NAME
            or not re.fullmatch(r"b64-064a-proxy-[0-9a-f]{20}",
                                socket_path.parent.name)
            or type(lifetime_seconds) is not int
            or not 1 <= lifetime_seconds
            <= activation.LIMITS["overallDeadlineSeconds"]
            or type(registration_fd) is not int or registration_fd < 3):
        return 21
    parent_pid = os.getppid()
    try:
        if ctypes.CDLL(None, use_errno=True).prctl(
                1, signal.SIGKILL, 0, 0, 0) != 0:
            return 24
        if os.getppid() != parent_pid:
            return 24
        registered = os.read(registration_fd, 2)
    except OSError:
        return 24
    finally:
        try:
            os.close(registration_fd)
        except OSError:
            pass
    if registered != b"G":
        return 24
    deadline = time.monotonic() + lifetime_seconds
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client: socket.socket | None = None
    upstream: socket.socket | None = None
    try:
        listener.bind(str(socket_path))
        os.chmod(socket_path, 0o600)
        os.chown(socket_path, 70, 70)
        listener.listen(1)
        listener.settimeout(max(0.1, deadline - time.monotonic()))
        client, _ = listener.accept()
        upstream = socket.create_connection(
            ("127.0.0.1", 5432),
            timeout=max(0.1, deadline - time.monotonic()),
        )
        client.setblocking(False)
        upstream.setblocking(False)
        selector = selectors.DefaultSelector()
        selector.register(client, selectors.EVENT_READ, upstream)
        selector.register(upstream, selectors.EVENT_READ, client)
        open_readers = {client, upstream}
        while open_readers:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return 22
            events = selector.select(min(remaining, 1.0))
            if not events:
                continue
            for key, _mask in events:
                source = key.fileobj
                destination = key.data
                try:
                    chunk = source.recv(64 * 1024)
                except BlockingIOError:
                    continue
                if not chunk:
                    selector.unregister(source)
                    open_readers.discard(source)
                    try:
                        destination.shutdown(socket.SHUT_WR)
                    except OSError:
                        pass
                    continue
                view = memoryview(chunk)
                while view:
                    if time.monotonic() >= deadline:
                        return 22
                    try:
                        sent = destination.send(view)
                        view = view[sent:]
                    except BlockingIOError:
                        time.sleep(0.001)
        return 0
    except (OSError, ValueError):
        return 23
    finally:
        for stream in (client, upstream, listener):
            if stream is not None:
                try:
                    stream.close()
                except OSError:
                    pass
        try:
            socket_path.unlink()
        except OSError:
            pass


class ExactProxy:
    def __init__(
        self, *, run_nonce: str, parent: Path, source_pid: int,
        source_netns_inode: int, deadline: float,
        executor_sha256: str,
        resource_journal: ExecutorResourceJournal,
    ) -> None:
        _safe_parent(parent, "PROXY_PARENT_UNSAFE")
        self.directory = parent / _proxy_name(run_nonce)
        self.socket_path = self.directory / PROXY_SOCKET_NAME
        self.deadline = deadline
        self.process: subprocess.Popen[bytes] | None = None
        self.source_pid = source_pid
        self.source_netns_inode = source_netns_inode
        self.executor_sha256 = executor_sha256
        self.resource_journal = resource_journal

    def start(self) -> None:
        try:
            self.directory.mkdir(mode=0o700)
            os.chown(self.directory, 70, 70)
        except OSError as exc:
            raise ExecutorError("PROXY_DIRECTORY_COLLISION") from exc
        script_fd = -1
        netns_fd = -1
        registration_read_fd = -1
        registration_write_fd = -1
        try:
            script_fd, _raw = _open_bound_artifact(
                Path(__file__), self.executor_sha256,
            )
            netns_fd = os.open(
                f"/proc/{self.source_pid}/ns/net",
                os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
            )
            if os.fstat(netns_fd).st_ino != self.source_netns_inode:
                raise ExecutorError("SOURCE_NETNS_BINDING_MISMATCH")
            registration_read_fd, registration_write_fd = os.pipe2(
                os.O_CLOEXEC
            )
            lifetime_seconds = min(
                max(1, int(self.deadline - time.monotonic())),
                activation.LIMITS["overallDeadlineSeconds"],
            )
            command = [
                NSENTER, f"--net=/proc/self/fd/{netns_fd}",
                PYTHON, f"/proc/self/fd/{script_fd}",
                "--proxy-helper", "--socket", str(self.socket_path),
                "--lifetime-seconds", str(lifetime_seconds),
                "--registration-fd", str(registration_read_fd),
            ]
            self.process = subprocess.Popen(
                command, stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                pass_fds=(script_fd, netns_fd, registration_read_fd),
                close_fds=True, env=MINIMAL_ENV,
            )
            try:
                start_time = int(
                    Path(f"/proc/{self.process.pid}/stat")
                    .read_text("ascii").split()[21]
                )
            except (OSError, ValueError, IndexError) as exc:
                raise ExecutorError("PROXY_PROCESS_BINDING_FAILED") from exc
            self.resource_journal.update(
                proxyPid=self.process.pid, proxyStartTime=start_time,
            )
            os.write(registration_write_fd, b"G")
        except BaseException:
            self.abort()
            raise
        finally:
            for descriptor in (
                registration_write_fd, registration_read_fd,
                netns_fd, script_fd,
            ):
                if descriptor >= 0:
                    try:
                        os.close(descriptor)
                    except OSError:
                        pass
        try:
            ready_deadline = min(
                self.deadline, time.monotonic() + 5.0
            )
            while time.monotonic() < ready_deadline:
                if self.process.poll() is not None:
                    raise ExecutorError("PROXY_HELPER_EARLY_EXIT")
                try:
                    metadata = self.socket_path.lstat()
                    if (stat.S_ISSOCK(metadata.st_mode)
                            and metadata.st_uid == 70
                            and stat.S_IMODE(metadata.st_mode) == 0o600):
                        return
                except FileNotFoundError:
                    pass
                time.sleep(0.02)
            raise ExecutorError("PROXY_HELPER_NOT_READY")
        except BaseException:
            self.abort()
            raise

    def close(self) -> None:
        process = self.process
        if process is not None:
            remaining = max(0.1, min(5.0, self.deadline - time.monotonic()))
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=2)
            if process.returncode != 0:
                raise ExecutorError("PROXY_HELPER_FAILED")
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        try:
            self.directory.rmdir()
        except OSError as exc:
            raise ExecutorError("PROXY_CLEANUP_UNCERTAIN") from exc
        self.resource_journal.update(proxyAbsent=True)

    def abort(self) -> None:
        process = self.process
        if process is not None and process.poll() is None:
            process.kill()
            try:
                process.wait(timeout=2)
            except subprocess.TimeoutExpired:
                pass
        try:
            self.socket_path.unlink()
        except OSError:
            pass
        try:
            self.directory.rmdir()
        except OSError:
            pass
        if not self.socket_path.exists() and not self.directory.exists():
            try:
                self.resource_journal.update(proxyAbsent=True)
            except ExecutorError:
                pass


class BoundDumpAdapter:
    def __init__(
        self, *, run_nonce: str, proxy_parent: Path,
        production_contact: bool, source_netns_inode: int,
        source_image_id: str, executor_sha256: str,
        resource_journal: ExecutorResourceJournal,
    ) -> None:
        self.run_nonce = run_nonce
        self.proxy_parent = proxy_parent
        self.production_contact = production_contact
        self.source_netns_inode = source_netns_inode
        self.source_image_id = source_image_id
        self.executor_sha256 = executor_sha256
        self.resource_journal = resource_journal
        self.container_id: str | None = None
        self.container_name = _dump_name(run_nonce)

    def _force_cleanup(self) -> None:
        observed = _inspect_container(
            self.container_id or self.container_name
        )
        if observed is None:
            return
        labels = observed.get("Labels") or {}
        observed_id = _container_id(observed.get("Id"))
        if (self.container_id is not None
                and observed_id != self.container_id):
            raise ExecutorError("DUMP_CLEANUP_BINDING_MISMATCH")
        if (observed.get("Name", "").lstrip("/") != self.container_name
                or labels.get("org.obsidian.run-nonce") != self.run_nonce
                or labels.get("org.obsidian.route") != DOCKER_ROUTE_LABEL):
            raise ExecutorError("DUMP_CLEANUP_BINDING_MISMATCH")
        stopped = _run(
            [DOCKER, "stop", "--time", "2", observed_id], text=True,
        )
        if stopped.returncode != 0:
            raise ExecutorError("DUMP_CLEANUP_FAILED")

    def run(
        self, plan: Mapping[str, Any], snapshot: str,
        source_container_id: str, credential_not_after_epoch: int,
        archive_fd: int, secret_fd: int, deadline: float,
    ) -> Mapping[str, Any]:
        source = _inspect_container(source_container_id)
        if (source is None
                or _container_id(source.get("Id")) != source_container_id
                or source.get("Image") != self.source_image_id
                or source.get("State", {}).get("Running") is not True):
            raise ExecutorError("DUMP_SOURCE_BINDING_MISMATCH")
        source_pid = source.get("State", {}).get("Pid")
        if type(source_pid) is not int or source_pid <= 1:
            raise ExecutorError("DUMP_SOURCE_BINDING_MISMATCH")
        preflight = _run(
            [DOCKER, *refresh.compile_client_preflight(plan)[1:]],
            text=True,
        )
        if (preflight.returncode != 0
                or preflight.stdout.strip() != refresh.PG_DUMP_VERSION
                or preflight.stderr):
            raise ExecutorError("PINNED_CLIENT_PREFLIGHT_FAILED")
        remaining = min(
            credential_not_after_epoch - time.time() - 5,
            deadline - time.monotonic() - 5,
        )
        transaction_timeout_ms = min(150_000, int(remaining * 1000))
        if transaction_timeout_ms < 1:
            raise ExecutorError("DUMP_DEADLINE_EXHAUSTED")
        command = refresh.compile_dump_command(
            plan, snapshot, source_container_id,
            transaction_timeout_ms=transaction_timeout_ms,
            lease_not_after_epoch=credential_not_after_epoch,
        )
        command[0] = DOCKER
        name_index = next(
            (index for index, item in enumerate(command)
             if item.startswith("--name=")), -1,
        )
        if name_index < 0:
            raise ExecutorError("DUMP_COMMAND_PROFILE_MISMATCH")
        command[name_index] = f"--name={self.container_name}"
        network_index = next(
            (index for index, item in enumerate(command)
             if item == f"--network=container:{source_container_id}"),
            -1,
        )
        if network_index < 0:
            raise ExecutorError("DUMP_COMMAND_PROFILE_MISMATCH")
        command[network_index] = "--network=none"
        proxy = ExactProxy(
            run_nonce=self.run_nonce, parent=self.proxy_parent,
            source_pid=source_pid,
            source_netns_inode=self.source_netns_inode,
            deadline=deadline, executor_sha256=self.executor_sha256,
            resource_journal=self.resource_journal,
        )
        image_index = command.index(refresh.IMAGE_REF)
        command.insert(
            image_index,
            "--mount=type=bind,src=" + str(proxy.directory)
            + ",dst=/run/b64/proxy,readonly",
        )
        old_dsn = next(
            (item for item in command
             if item.startswith("--dbname=postgresql://")), None,
        )
        if old_dsn is None:
            proxy.abort()
            raise ExecutorError("DUMP_COMMAND_PROFILE_MISMATCH")
        new_dsn = old_dsn.replace(
            "@127.0.0.1:5432/", "@%2Frun%2Fb64%2Fproxy/"
        )
        if new_dsn == old_dsn:
            proxy.abort()
            raise ExecutorError("DUMP_COMMAND_PROFILE_MISMATCH")
        command[command.index(old_dsn)] = new_dsn
        stderr_fd = os.memfd_create(
            "b64-064a-pgdump-stderr", os.MFD_CLOEXEC
        )
        try:
            proxy.start()
            with tempfile.TemporaryDirectory(
                    prefix="b64-activation-cid-", dir="/tmp") as cid_root:
                cid_path = Path(cid_root) / "container.id"
                command.insert(2, f"--cidfile={cid_path}")

                def limit_output() -> None:
                    resource.setrlimit(
                        resource.RLIMIT_FSIZE,
                        (activation.LIMITS["maximumArchiveBytes"],
                         activation.LIMITS["maximumArchiveBytes"]),
                    )

                completed = subprocess.run(
                    command, stdin=secret_fd, stdout=archive_fd,
                    stderr=stderr_fd, check=False,
                    timeout=max(0.1, deadline - time.monotonic()),
                    env=MINIMAL_ENV, preexec_fn=limit_output,
                )
                try:
                    container_id = cid_path.read_text("ascii").strip()
                except OSError as exc:
                    raise ExecutorError("DUMP_CONTAINER_ID_MISSING") from exc
                self.container_id = _container_id(container_id)
                self.resource_journal.update(
                    dumpContainerId=self.container_id,
                )
            stderr_size = os.fstat(stderr_fd).st_size
            os.lseek(stderr_fd, 0, os.SEEK_SET)
            stderr_raw = os.read(stderr_fd, min(stderr_size, MAX_STDERR_BYTES + 1))
            proxy.close()
            if completed.returncode != 0:
                lowered = stderr_raw.lower()
                if b"permission denied" in lowered:
                    reason = "DUMP_PROXY_PERMISSION_DENIED"
                elif b"no such file or directory" in lowered:
                    reason = "DUMP_PROXY_SOCKET_MISSING"
                elif b"password authentication failed" in lowered:
                    reason = "DUMP_AUTHENTICATION_FAILED"
                elif b"no password supplied" in lowered:
                    reason = "DUMP_PASSWORD_FILE_MISMATCH"
                elif b"connection to server" in lowered:
                    reason = "DUMP_CONNECTION_FAILED"
                else:
                    reason = "DUMP_PROCESS_FAILED"
                raise ExecutorError(reason)
            if stderr_size != 0 or stderr_raw:
                raise ExecutorError("DUMP_STDERR_PRESENT")
            if _inspect_container(self.container_id) is not None:
                raise ExecutorError("DUMP_CONTAINER_RETAINED")
            return {
                "clientVersion": refresh.PG_DUMP_VERSION,
                "exitCode": 0, "stderrBytes": 0,
                "stderrSha256": hashlib.sha256(b"").hexdigest(),
                "warningCount": 0,
                "sourceContainerId": source_container_id,
                "containerId": self.container_id,
            }
        except BaseException:
            proxy.abort()
            self._force_cleanup()
            raise
        finally:
            os.close(stderr_fd)

    def cleanup(self, expected_container_id: str | None) -> Mapping[str, Any]:
        if expected_container_id != self.container_id:
            raise ExecutorError("DUMP_CLEANUP_BINDING_MISMATCH")
        self._force_cleanup()
        absent = (
            _inspect_container(expected_container_id) is None
            and _inspect_container(self.container_name) is None
        )
        if absent:
            self.resource_journal.update(dumpAbsent=True)
        return {
            "containerId": expected_container_id,
            "containerAbsent": absent,
            "tmpfsReleased": absent,
        }


class BoundRestoreAdapter:
    production_contact = False

    def __init__(
        self, *, run_nonce: str,
        resource_journal: ExecutorResourceJournal,
    ) -> None:
        self.run_nonce = run_nonce
        self.container_id: str | None = None
        self.container_name = _restore_name(run_nonce)
        self.resource_journal = resource_journal

    def _force_cleanup(self) -> None:
        observed = _inspect_container(
            self.container_id or self.container_name
        )
        if observed is None:
            return
        candidate = _container_id(observed.get("Id"))
        labels = observed.get("Labels") or {}
        if (self.container_id is not None
                and candidate != self.container_id):
            raise ExecutorError("RESTORE_CLEANUP_BINDING_MISMATCH")
        if (observed.get("Name", "").lstrip("/") != self.container_name
                or labels.get("org.obsidian.run-nonce") != self.run_nonce
                or labels.get("org.obsidian.route") != DOCKER_ROUTE_LABEL):
            raise ExecutorError("RESTORE_CLEANUP_BINDING_MISMATCH")
        stopped = _run(
            [DOCKER, "stop", "--time", "2", candidate], text=True,
        )
        if stopped.returncode != 0:
            raise ExecutorError("RESTORE_CLEANUP_FAILED")

    def _start(self, deadline: float) -> None:
        command = [
            DOCKER, "run", "-d", "--rm", "--pull=never",
            "--platform=linux/amd64", f"--name={self.container_name}",
            f"--label=org.obsidian.route={DOCKER_ROUTE_LABEL}",
            f"--label=org.obsidian.run-nonce={self.run_nonce}",
            "--network=none", "--read-only", "--user=70:70",
            "--cap-drop=ALL", "--security-opt=no-new-privileges=true",
            "--pids-limit=128", "--memory=512m", "--cpus=1",
            "--tmpfs=/var/lib/postgresql/data:rw,nosuid,nodev,size=256m,"
            "mode=0700,uid=70,gid=70",
            "--tmpfs=/run/postgresql:rw,nosuid,nodev,size=1m,"
            "mode=0770,uid=70,gid=70",
            "--tmpfs=/tmp:rw,noexec,nosuid,nodev,size=16m,mode=1777",
            "--env=POSTGRES_DB=obsidian_exchange",
            "--env=POSTGRES_HOST_AUTH_METHOD=trust",
            refresh.IMAGE_REF,
        ]
        started = _run(command, text=True)
        if started.returncode != 0 or started.stderr:
            raise ExecutorError("RESTORE_CONTAINER_START_FAILED")
        self.container_id = _container_id(started.stdout.strip())
        self.resource_journal.update(
            restoreContainerId=self.container_id,
        )
        readiness_deadline = min(deadline, time.monotonic() + 20.0)
        while time.monotonic() < readiness_deadline:
            ready = _run([
                DOCKER, "exec", self.container_id, "pg_isready", "-q",
                "-U", "postgres", "-d", "obsidian_exchange",
            ])
            if ready.returncode == 0:
                return
            observed = _inspect_container(self.container_id)
            if observed is None or not observed.get("State", {}).get("Running"):
                raise ExecutorError("RESTORE_CONTAINER_EARLY_EXIT")
            time.sleep(0.1)
        raise ExecutorError("RESTORE_CONTAINER_NOT_READY")

    def verify(
        self, plan: Mapping[str, Any], archive_fd: int,
        workspace_fd: int, source_fingerprints: Mapping[str, Any],
        deadline: float,
    ) -> Mapping[str, Any]:
        source_tables = source_fingerprints.get("tables")
        source_catalog = source_fingerprints.get("catalog")
        source_system_identifier = source_fingerprints.get(
            "systemIdentifier"
        )
        artifacts = plan.get("artifactsSha256")
        if (type(source_tables) is not list or len(source_tables) != 54
                or type(source_catalog) is not list
                or len(source_catalog) != 13
                or hashlib.sha256(activation._canonical(source_tables))
                .hexdigest() != source_fingerprints.get("tableSha256")
                or hashlib.sha256(activation._canonical(source_catalog))
                .hexdigest() != source_fingerprints.get("catalogSha256")
                or type(source_system_identifier) is not str
                or not isinstance(artifacts, Mapping)):
            raise ExecutorError("RESTORE_SOURCE_FINGERPRINT_INVALID")
        try:
            bootstrap_roles_sql = _read_bound_artifact(
                POSTGRES / "bootstrap_roles.sql",
                artifacts["bootstrapRolesSql"],
            ).decode("utf-8")
            prepare_database_sql = _read_bound_artifact(
                POSTGRES / "prepare_database.sql",
                artifacts["prepareDatabaseSql"],
            ).decode("utf-8")
            runtime_privileges_sql = _read_bound_artifact(
                POSTGRES / "runtime_privileges.sql",
                artifacts["runtimePrivilegesSql"],
            ).decode("utf-8")
            provision_sql = _read_bound_artifact(
                POSTGRES / "provision_b64_snapshot_reader.sql",
                artifacts["snapshotReaderProvisionSql"],
            ).decode("utf-8")
            catalog_sql_raw = _read_bound_artifact(
                POSTGRES / "b64_catalog_security_fingerprint.sql",
                artifacts["catalogFingerprintSql"],
            )
        except (KeyError, UnicodeDecodeError) as exc:
            raise ExecutorError("RESTORE_ARTIFACT_CLOSURE_INVALID") from exc
        stage = "START"
        socket_directory_fd = -1
        try:
            self._start(deadline)
            observed = _inspect_container(self.container_id)
            if observed is None:
                raise ExecutorError("RESTORE_CONTAINER_MISSING")
            container_pid = observed.get("State", {}).get("Pid")
            if type(container_pid) is not int or container_pid <= 1:
                raise ExecutorError("RESTORE_CONTAINER_MISSING")
            stage = "SOCKET_BIND"
            socket_directory_fd = os.open(
                f"/proc/{container_pid}/root/run/postgresql",
                os.O_RDONLY | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            socket_metadata = os.fstat(socket_directory_fd)
            rebound = _inspect_container(self.container_id)
            if (not stat.S_ISDIR(socket_metadata.st_mode)
                    or socket_metadata.st_uid != 70
                    or stat.S_IMODE(socket_metadata.st_mode) != 0o3775
                    or rebound is None
                    or rebound.get("State", {}).get("Running") is not True
                    or rebound.get("State", {}).get("Pid") != container_pid):
                raise ExecutorError("RESTORE_SOCKET_BINDING_MISMATCH")
            restore_dsn = make_conninfo(
                host=f"/proc/self/fd/{socket_directory_fd}",
                dbname="obsidian_exchange", user="postgres", port=5432,
                connect_timeout=5, sslmode="disable",
                target_session_attrs="read-write",
            )
            identity = None
            identity_deadline = min(deadline, time.monotonic() + 5.0)
            while identity is None and time.monotonic() < identity_deadline:
                try:
                    with psycopg.connect(restore_dsn) as identity_conn:
                        identity = identity_conn.execute(
                            "SELECT current_user,current_database(),"
                            "current_setting('server_version_num')::int/10000,"
                            "current_setting('server_encoding'),"
                            "system_identifier::text FROM pg_control_system()"
                        ).fetchone()
                except psycopg.OperationalError:
                    time.sleep(0.1)
            if (identity is None or identity[:4] != (
                    "postgres", "obsidian_exchange", 17, "UTF8")
                    or identity[4] == source_system_identifier):
                raise ExecutorError("RESTORE_SOCKET_IDENTITY_MISMATCH")
            stage = "BOOTSTRAP_ROLES"
            with psycopg.connect(restore_dsn, autocommit=True) as conn:
                conn.execute(bootstrap_roles_sql)
            stage = "PREPARE_DATABASE"
            with psycopg.connect(restore_dsn) as conn:
                conn.execute(prepare_database_sql)
                counts = conn.execute(
                    "SELECT (SELECT count(*) FROM pg_class c JOIN "
                    "pg_namespace n ON n.oid=c.relnamespace WHERE "
                    "n.nspname='public'),(SELECT count(*) FROM pg_proc p "
                    "JOIN pg_namespace n ON n.oid=p.pronamespace WHERE "
                    "n.nspname='public'),(SELECT count(*) FROM pg_type t "
                    "JOIN pg_namespace n ON n.oid=t.typnamespace WHERE "
                    "n.nspname='public' AND t.typtype<>'p')"
                ).fetchone()
                if counts != (0, 0, 0):
                    raise ExecutorError("RESTORE_TARGET_SCHEMA_NOT_EMPTY")
                conn.execute("DROP SCHEMA public")
            stage = "PG_RESTORE"
            os.lseek(archive_fd, 0, os.SEEK_SET)
            stderr_fd = os.memfd_create(
                "b64-064a-pgrestore-stderr", os.MFD_CLOEXEC
            )
            try:
                def limit_restore_stderr() -> None:
                    resource.setrlimit(
                        resource.RLIMIT_FSIZE,
                        (MAX_STDERR_BYTES, MAX_STDERR_BYTES),
                    )

                restored = subprocess.run(
                    [
                        DOCKER, "exec", "-i", self.container_id,
                        "pg_restore", "--username=postgres",
                        "--dbname=obsidian_exchange",
                        "--role=obsidian_migrator", "--no-owner",
                        "--no-privileges", "--exit-on-error",
                    ],
                    stdin=archive_fd, stdout=subprocess.DEVNULL,
                    stderr=stderr_fd, check=False, env=MINIMAL_ENV,
                    timeout=max(0.1, deadline - time.monotonic()),
                    preexec_fn=limit_restore_stderr,
                )
                stderr_size = os.fstat(stderr_fd).st_size
            finally:
                os.close(stderr_fd)
            if restored.returncode != 0 or stderr_size != 0:
                raise ExecutorError("PG_RESTORE_FAILED")
            stage = "RUNTIME_PRIVILEGES"
            with psycopg.connect(restore_dsn, autocommit=True) as conn:
                conn.execute(runtime_privileges_sql)
                _execute_bound(
                    conn, provision_sql,
                    "obsidian_exchange",
                )
            stage = "FINGERPRINT"
            catalog_fd = os.memfd_create(
                "b64-064a-restore-catalog-sql", os.MFD_CLOEXEC
            )
            os.fchmod(catalog_fd, 0o600)
            os.write(catalog_fd, catalog_sql_raw)
            os.lseek(catalog_fd, 0, os.SEEK_SET)
            with psycopg.connect(restore_dsn) as conn:
                try:
                    restore_tables, _ = runtime._source_table_fingerprint(conn)
                    restore_catalog, _ = runtime._source_catalog_fingerprint(
                        conn, catalog_fd
                    )
                    restore_system_identifier = conn.execute(
                        "SELECT system_identifier::text "
                        "FROM pg_control_system()"
                    ).fetchone()[0]
                finally:
                    os.close(catalog_fd)
            _write_manifest(
                workspace_fd, "source-table-fingerprint.json", source_tables,
            )
            _write_manifest(
                workspace_fd, "restore-table-fingerprint.json", restore_tables,
            )
            _write_manifest(
                workspace_fd, "source-catalog-fingerprint.json", source_catalog,
            )
            _write_manifest(
                workspace_fd, "restore-catalog-fingerprint.json", restore_catalog,
            )
            os.close(socket_directory_fd)
            socket_directory_fd = -1
            return {
                "tables": len(restore_tables),
                "catalogSections": len(restore_catalog),
                "tableMatch": restore_tables == source_tables,
                "catalogMatch": restore_catalog == source_catalog,
                "restoreClusterDistinct": restore_system_identifier
                != source_system_identifier,
                "sequenceRuntimeStateCompared": False,
                "restoreNoOwnerApplied": True,
                "restoreNoPrivilegesApplied": True,
                "containerId": self.container_id,
            }
        except BaseException as exc:
            if socket_directory_fd >= 0:
                os.close(socket_directory_fd)
            self._force_cleanup()
            if isinstance(exc, (ExecutorError, refresh.HardenedRefreshError)):
                raise
            raise ExecutorError(f"RESTORE_{stage}_FAILURE") from exc

    def cleanup(self, expected_container_id: str | None) -> Mapping[str, Any]:
        if expected_container_id != self.container_id:
            raise ExecutorError("RESTORE_CLEANUP_BINDING_MISMATCH")
        self._force_cleanup()
        absent = (
            _inspect_container(expected_container_id) is None
            and _inspect_container(self.container_name) is None
        )
        if absent:
            self.resource_journal.update(restoreAbsent=True)
        return {
            "containerId": expected_container_id,
            "containerAbsent": absent,
            "tmpfsReleased": absent,
        }


class BoundActivationExecutor:
    """One exact executor implementation for contract and production modes."""

    def __init__(
        self, *, production_contact: bool, observation_dsn: str,
        admin_dsn: str, container: str, container_id: str,
        image_id: str, system_identifier: str,
        workspace_parent: Path, proxy_parent: Path,
        resource_journal_root: Path,
    ) -> None:
        self.production_contact = production_contact
        self.observation_dsn = observation_dsn
        self.admin_dsn = admin_dsn
        self.container = container
        self.container_id = _container_id(container_id)
        self.image_id = image_id
        self.system_identifier = system_identifier
        self.workspace_parent = workspace_parent
        self.proxy_parent = proxy_parent
        self.resource_journal_root = resource_journal_root
        self.calls = 0
        _safe_parent(workspace_parent, "WORKSPACE_PARENT_UNSAFE")
        _safe_parent(proxy_parent, "PROXY_PARENT_UNSAFE")
        _safe_parent(
            resource_journal_root, "EXECUTOR_JOURNAL_ROOT_UNSAFE"
        )
        if production_contact:
            if (container != activation.PRODUCTION_CONTAINER
                    or image_id != activation.PRODUCTION_IMAGE_ID
                    or system_identifier
                    != activation.PRODUCTION_SYSTEM_IDENTIFIER
                    or workspace_parent
                    != activation.PRODUCTION_WORKSPACE_ROOT
                    or proxy_parent != activation.PRODUCTION_PROXY_ROOT
                    or resource_journal_root
                    != activation.PRODUCTION_RESOURCE_JOURNAL_ROOT):
                raise ExecutorError("PRODUCTION_EXECUTOR_BINDING_MISMATCH")
        elif re.fullmatch(activation.CONTRACT_CONTAINER_PATTERN, container) \
                is None:
            raise ExecutorError("CONTRACT_EXECUTOR_BINDING_MISMATCH")

    def _close_execution(
        self, *, receipt: Mapping[str, Any],
        verified: activation.VerifiedActivation,
        resources: ExecutorResourceJournal, deadline: float,
    ) -> Mapping[str, Any]:
        if (receipt.get("status") != "COMPLETED"
                or receipt.get("cleanupStatus") != "CLEANUP_VERIFIED"
                or time.monotonic() > deadline):
            reason = receipt.get("errorCode") or "UNKNOWN"
            if type(reason) is not str or re.fullmatch(
                    r"[A-Z0-9_]+", reason) is None:
                reason = "UNSAFE_OR_MISSING_REASON"
            raise ExecutorError(f"HARDENED_EXECUTION_{reason}")
        closed = inspect(self.admin_dsn)
        closed_sessions = runtime._role_auth_state(
            self.admin_dsn
        )["sessions"]
        cleanup = receipt["cleanup"]
        resources.update(
            state="CLOSED", credentialReconciled=True,
            workspaceAbsent=cleanup["workspaceAbsent"],
            proxyAbsent=True,
            dumpAbsent=cleanup["dumpContainerAbsent"],
            restoreAbsent=cleanup["restoreContainerAbsent"],
        )
        return {
            "schemaVersion": activation.EXECUTION_RECEIPT_SCHEMA,
            "route": activation.ROUTE,
            "environment": verified.environment,
            "runNonce": verified.run_nonce,
            "planSha256": verified.plan_sha256,
            "decisionSha256": verified.decision_sha256,
            "status": "COMPLETED_DORMANT_VERIFIED",
            "archiveBytes": receipt["archiveBytes"],
            "archiveSha256": receipt["archiveSha256"],
            "catalogEquality": True, "tableEquality": True,
            "credentialIssued": True,
            "credentialRevoked": cleanup["credentialRevocationAttested"],
            "sourceSessionClosed": cleanup["sourceSessionClosed"],
            "readerLoginState": closed["loginState"],
            "readerCredentialState": closed["credentialState"],
            "readerActiveSessions": closed_sessions,
            "registeredWorkspaceAbsent": cleanup["workspaceAbsent"],
            "dumpContainerAbsent": cleanup["dumpContainerAbsent"],
            "restoreContainerAbsent": cleanup["restoreContainerAbsent"],
            "containerTmpfsLifetimesEnded": cleanup[
                "containerTmpfsLifetimesEnded"
            ],
            "productionDataRetained": False,
            "automaticRetryAllowed": False, "actionAllowed": False,
        }

    def execute(
        self, plan: Mapping[str, Any],
        authorization: activation.VerifiedActivation, deadline: float,
    ) -> Mapping[str, Any]:
        self.calls += 1
        expected_environment = (
            "PRODUCTION" if self.production_contact
            else "DISPOSABLE_CONTRACT"
        )
        verified = activation.require_verified_execution_authorization(
            authorization, expected_environment=expected_environment,
        )
        target = plan.get("target")
        if (self.calls != 1 or not isinstance(target, Mapping)
                or target != verified.target
                or target.get("containerName") != self.container
                or target.get("containerId") != self.container_id
                or target.get("imageId") != self.image_id
                or target.get("systemIdentifier") != self.system_identifier
                or type(deadline) is not float
                or not time.monotonic() < deadline
                <= time.monotonic()
                + activation.LIMITS["workDeadlineSeconds"] + 1):
            raise ExecutorError("EXECUTOR_ACTIVATION_BINDING_FAILED")
        derived_plan = activation.derive_execution_plan(
            run_nonce=verified.run_nonce,
            artifacts_sha256=plan["artifactsSha256"],
        )
        derived_sha = hashlib.sha256(
            activation._canonical(derived_plan)
        ).hexdigest()
        if derived_sha != verified.derived_execution_plan_sha256:
            raise ExecutorError("EXECUTOR_DERIVED_PLAN_MISMATCH")
        resources = ExecutorResourceJournal(
            root=self.resource_journal_root,
            run_nonce=verified.run_nonce,
            environment=verified.environment, target=verified.target,
            plan_sha256=verified.plan_sha256,
            decision_sha256=verified.decision_sha256,
            derived_plan_sha256=verified.derived_execution_plan_sha256,
        )
        resources.create()
        lease = None
        try:
            lease = runtime.issue_credential_lease(
                observation_dsn=self.observation_dsn,
                admin_dsn=self.admin_dsn, container=self.container,
                expected_container_id=self.container_id,
                expected_image_id=self.image_id,
                ttl_seconds=activation.LIMITS["credentialTtlSeconds"],
                allow_contract_container=not self.production_contact,
                production_authorization=(
                    verified if self.production_contact else None
                ),
                execution_plan=derived_plan,
            )
            resources.update(state="RUNNING", credentialIssued=True)
            source = runtime.ProductionSourceAdapter(
                lease, frozen_plan=derived_plan,
            )
            dump = BoundDumpAdapter(
                run_nonce=verified.run_nonce,
                proxy_parent=self.proxy_parent,
                production_contact=self.production_contact,
                source_netns_inode=lease.source_netns_inode,
                source_image_id=self.image_id,
                executor_sha256=plan["artifactsSha256"][
                    "activationExecutor"
                ],
                resource_journal=resources,
            )
            restore = BoundRestoreAdapter(
                run_nonce=verified.run_nonce,
                resource_journal=resources,
            )
            if self.production_contact:
                receipt = refresh.execute_authorized(
                    derived_plan, self.workspace_parent,
                    source=source, dump=dump, restore=restore,
                    source_secret_fd=lease.source_fd,
                    dump_secret_fd=lease.dump_fd,
                    authorization=verified, absolute_deadline=deadline,
                    workspace_registered=lambda dev, ino: resources.update(
                        workspaceDev=dev, workspaceIno=ino,
                    ),
                )
            else:
                receipt = refresh.execute_hermetic(
                    derived_plan, self.workspace_parent,
                    source=source, dump=dump, restore=restore,
                    source_secret_fd=lease.source_fd,
                    dump_secret_fd=lease.dump_fd,
                    absolute_deadline=deadline,
                    workspace_registered=lambda dev, ino: resources.update(
                        workspaceDev=dev, workspaceIno=ino,
                    ),
                )
        except BaseException:
            try:
                resources.update(state="HOLD")
            except BaseException:
                pass
            raise
        finally:
            if lease is not None:
                try:
                    lease.close()
                except BaseException:
                    try:
                        resources.update(state="HOLD")
                    except BaseException:
                        pass
                    raise
        try:
            return self._close_execution(
                receipt=receipt, verified=verified,
                resources=resources, deadline=deadline,
            )
        except BaseException:
            try:
                resources.update(state="HOLD")
            except BaseException:
                pass
            raise

    def _reconcile_container(
        self, *, name: str, container_id: str | None,
        run_nonce: str,
    ) -> bool:
        observed = _inspect_container(container_id or name)
        if observed is None and container_id is not None:
            observed = _inspect_container(name)
        if observed is None:
            return True
        labels = observed.get("Labels") or {}
        observed_id = _container_id(observed.get("Id"))
        if (observed.get("Name", "").lstrip("/") != name
                or (container_id is not None
                    and observed_id != container_id)
                or labels.get("org.obsidian.run-nonce") != run_nonce
                or labels.get("org.obsidian.route")
                != DOCKER_ROUTE_LABEL):
            raise ExecutorError("RECONCILE_CONTAINER_BINDING_MISMATCH")
        stopped = _run(
            [DOCKER, "stop", "--time", "2", observed_id],
            text=True, timeout=5,
        )
        if stopped.returncode != 0:
            raise ExecutorError("RECONCILE_CONTAINER_STOP_FAILED")
        return (
            _inspect_container(observed_id) is None
            and _inspect_container(name) is None
        )

    def _reconcile_proxy(self, value: Mapping[str, Any]) -> bool:
        directory = self.proxy_parent / value["proxyName"]
        socket_path = directory / PROXY_SOCKET_NAME
        pid = value.get("proxyPid")
        start_time = value.get("proxyStartTime")
        if pid is not None:
            if type(pid) is not int or type(start_time) is not int:
                raise ExecutorError("RECONCILE_PROXY_BINDING_MISMATCH")
            proc = Path(f"/proc/{pid}")
            if proc.exists():
                try:
                    metadata = proc.stat()
                    observed_start = int(
                        (proc / "stat").read_text("ascii").split()[21]
                    )
                    command = (proc / "cmdline").read_bytes().split(b"\0")
                except (OSError, ValueError, IndexError) as exc:
                    raise ExecutorError(
                        "RECONCILE_PROXY_BINDING_MISMATCH"
                    ) from exc
                if (metadata.st_uid != 0 or observed_start != start_time
                        or b"--proxy-helper" not in command
                        or str(socket_path).encode("utf-8") not in command):
                    raise ExecutorError(
                        "RECONCILE_PROXY_BINDING_MISMATCH"
                    )
                os.kill(pid, signal.SIGKILL)
                deadline = time.monotonic() + 2
                while proc.exists() and time.monotonic() < deadline:
                    time.sleep(0.02)
                if proc.exists():
                    raise ExecutorError("RECONCILE_PROXY_KILL_FAILED")
        parent_fd = os.open(
            self.proxy_parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        directory_fd = -1
        try:
            try:
                metadata = os.stat(
                    value["proxyName"], dir_fd=parent_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                return _path_entry_absent(socket_path)
            if (not stat.S_ISDIR(metadata.st_mode)
                    or metadata.st_uid != 70
                    or stat.S_IMODE(metadata.st_mode) != 0o700):
                raise ExecutorError("RECONCILE_PROXY_BINDING_MISMATCH")
            directory_fd = os.open(
                value["proxyName"], os.O_RDONLY | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd,
            )
            try:
                socket_metadata = os.stat(
                    PROXY_SOCKET_NAME, dir_fd=directory_fd,
                    follow_symlinks=False,
                )
            except FileNotFoundError:
                socket_metadata = None
            if socket_metadata is not None:
                if (not stat.S_ISSOCK(socket_metadata.st_mode)
                        or socket_metadata.st_uid != 70
                        or stat.S_IMODE(socket_metadata.st_mode) != 0o600):
                    raise ExecutorError(
                        "RECONCILE_PROXY_BINDING_MISMATCH"
                    )
                os.unlink(PROXY_SOCKET_NAME, dir_fd=directory_fd)
            if os.listdir(directory_fd):
                raise ExecutorError("RECONCILE_PROXY_BINDING_MISMATCH")
            os.fsync(directory_fd)
            os.rmdir(value["proxyName"], dir_fd=parent_fd)
            os.fsync(parent_fd)
            if os.fstat(directory_fd).st_nlink != 0:
                raise ExecutorError("RECONCILE_PROXY_DURABILITY_UNCERTAIN")
            return _path_entry_absent(directory)
        finally:
            if directory_fd >= 0:
                os.close(directory_fd)
            os.close(parent_fd)

    def _reconcile_workspace(self, value: Mapping[str, Any]) -> bool:
        name = value["workspaceName"]
        expected_inode = (value.get("workspaceDev"), value.get("workspaceIno"))
        parent_fd = os.open(
            self.workspace_parent,
            os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
            | getattr(os, "O_CLOEXEC", 0),
        )
        directory_fd = -1
        try:
            try:
                named = os.stat(name, dir_fd=parent_fd, follow_symlinks=False)
            except FileNotFoundError:
                return True
            if (None in expected_inode
                    or not stat.S_ISDIR(named.st_mode)
                    or (named.st_dev, named.st_ino) != expected_inode
                    or named.st_uid != os.geteuid()
                    or stat.S_IMODE(named.st_mode) != 0o700):
                raise ExecutorError("RECONCILE_WORKSPACE_BINDING_MISMATCH")
            directory_fd = os.open(
                name, os.O_RDONLY | os.O_DIRECTORY
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0), dir_fd=parent_fd,
            )
            bound = os.fstat(directory_fd)
            if (bound.st_dev, bound.st_ino) != expected_inode:
                raise ExecutorError("RECONCILE_WORKSPACE_BINDING_MISMATCH")
            entries = os.listdir(directory_fd)
            if any(item not in refresh.TRANSIENT_NAMES for item in entries):
                raise ExecutorError("RECONCILE_WORKSPACE_FOREIGN_ENTRY")
            for item in entries:
                metadata = os.stat(
                    item, dir_fd=directory_fd, follow_symlinks=False,
                )
                if (not stat.S_ISREG(metadata.st_mode)
                        or metadata.st_uid != os.geteuid()
                        or stat.S_IMODE(metadata.st_mode) != 0o600
                        or metadata.st_nlink != 1):
                    raise ExecutorError(
                        "RECONCILE_WORKSPACE_BINDING_MISMATCH"
                    )
                os.unlink(item, dir_fd=directory_fd)
            os.fsync(directory_fd)
            os.rmdir(name, dir_fd=parent_fd)
            os.fsync(parent_fd)
            rebound = os.fstat(directory_fd)
            if ((rebound.st_dev, rebound.st_ino) != expected_inode
                    or rebound.st_nlink != 0
                    or not _path_entry_absent(
                        self.workspace_parent / name
                    )):
                raise ExecutorError("RECONCILE_WORKSPACE_DURABILITY_UNCERTAIN")
            return True
        finally:
            if directory_fd >= 0:
                os.close(directory_fd)
            os.close(parent_fd)

    def reconcile_resources(
        self, *, plan: Mapping[str, Any],
        authorization: activation.VerifiedActivation,
    ) -> Mapping[str, Any]:
        expected_environment = (
            "PRODUCTION" if self.production_contact
            else "DISPOSABLE_CONTRACT"
        )
        verified = activation.require_verified_execution_authorization(
            authorization, expected_environment=expected_environment,
            require_started=False,
        )
        derived_plan = activation.derive_execution_plan(
            run_nonce=verified.run_nonce,
            artifacts_sha256=plan["artifactsSha256"],
        )
        if hashlib.sha256(activation._canonical(derived_plan)).hexdigest() \
                != verified.derived_execution_plan_sha256:
            raise ExecutorError("RECONCILE_EXECUTION_PLAN_MISMATCH")
        resources = ExecutorResourceJournal(
            root=self.resource_journal_root,
            run_nonce=verified.run_nonce,
            environment=verified.environment, target=verified.target,
            plan_sha256=verified.plan_sha256,
            decision_sha256=verified.decision_sha256,
            derived_plan_sha256=verified.derived_execution_plan_sha256,
        )
        current = resources.inspect_optional()
        if current is not None and current["state"] not in {
                "PREPARED", "RUNNING", "HOLD", "CLOSED",
                "RECONCILED_HOLD"}:
            raise ExecutorError("RECONCILE_RESOURCE_STATE_INVALID")
        if current is not None and current["state"] in {
                "PREPARED", "RUNNING"}:
            current = resources.update(state="HOLD")
        credential = runtime.reconcile_credential(
            observation_dsn=self.observation_dsn,
            admin_dsn=self.admin_dsn, container=self.container,
            expected_container_id=self.container_id,
            expected_image_id=self.image_id,
            allow_contract_container=not self.production_contact,
            execution_plan=derived_plan,
        )
        if current is None:
            names = {
                "workspace": self.workspace_parent
                / f"b64-064a-{verified.run_nonce}",
                "proxy": self.proxy_parent / _proxy_name(verified.run_nonce),
            }
            dump_absent = _inspect_container(
                _dump_name(verified.run_nonce)
            ) is None
            restore_absent = _inspect_container(
                _restore_name(verified.run_nonce)
            ) is None
            workspace_absent = _path_entry_absent(names["workspace"])
            proxy_absent = _path_entry_absent(names["proxy"])
            if (credential.get("loginState") != "DISABLED"
                    or credential.get("credentialState") != "ABSENT"
                    or credential.get("activeSessions") != 0
                    or not all((workspace_absent, proxy_absent, dump_absent,
                                restore_absent))):
                raise ExecutorError(
                    "RECONCILE_RESOURCE_JOURNAL_ABSENT_WITH_RESOURCES"
                )
            return {
                "status": "EXECUTOR_RESOURCES_ABSENT_NO_JOURNAL",
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "workspaceAbsent": True,
                "proxyAbsent": True, "dumpAbsent": True,
                "restoreAbsent": True, "automaticRetryAllowed": False,
                "actionAllowed": False,
            }
        if current["state"] in {"CLOSED", "RECONCILED_HOLD"}:
            workspace_absent = _path_entry_absent(
                self.workspace_parent / current["workspaceName"]
            )
            proxy_absent = _path_entry_absent(
                self.proxy_parent / current["proxyName"]
            )
            dump_absent = _inspect_container(current["dumpName"]) is None
            restore_absent = _inspect_container(
                current["restoreName"]
            ) is None
            if (credential.get("loginState") != "DISABLED"
                    or credential.get("credentialState") != "ABSENT"
                    or credential.get("activeSessions") != 0
                    or not all(current[name] for name in (
                        "workspaceAbsent", "proxyAbsent", "dumpAbsent",
                        "restoreAbsent",
                    ))
                    or not all((workspace_absent, proxy_absent, dump_absent,
                                restore_absent))):
                raise ExecutorError("RECONCILE_CLOSED_RESOURCES_UNCERTAIN")
            return {
                "status": (
                    "EXECUTOR_RESOURCES_ALREADY_CLOSED"
                    if current["state"] == "CLOSED" else
                    "EXECUTOR_RESOURCES_RECONCILED_HOLD"
                ),
                "loginState": "DISABLED", "credentialState": "ABSENT",
                "activeSessions": 0, "workspaceAbsent": True,
                "proxyAbsent": True, "dumpAbsent": True,
                "restoreAbsent": True, "automaticRetryAllowed": False,
                "actionAllowed": False,
            }
        proxy_absent = self._reconcile_proxy(current)
        dump_absent = self._reconcile_container(
            name=current["dumpName"],
            container_id=current["dumpContainerId"],
            run_nonce=verified.run_nonce,
        )
        restore_absent = self._reconcile_container(
            name=current["restoreName"],
            container_id=current["restoreContainerId"],
            run_nonce=verified.run_nonce,
        )
        workspace_absent = self._reconcile_workspace(current)
        if (credential.get("loginState") != "DISABLED"
                or credential.get("credentialState") != "ABSENT"
                or credential.get("activeSessions") != 0
                or not all((proxy_absent, dump_absent, restore_absent,
                            workspace_absent))):
            raise ExecutorError("RECONCILE_RESOURCES_UNCERTAIN")
        resources.update(
            state="RECONCILED_HOLD", credentialReconciled=True,
            workspaceAbsent=True, proxyAbsent=True, dumpAbsent=True,
            restoreAbsent=True,
        )
        return {
            "status": "EXECUTOR_RESOURCES_RECONCILED_HOLD",
            "loginState": "DISABLED", "credentialState": "ABSENT",
            "activeSessions": 0, "workspaceAbsent": True,
            "proxyAbsent": True, "dumpAbsent": True,
            "restoreAbsent": True, "automaticRetryAllowed": False,
            "actionAllowed": False,
        }


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("--proxy-helper", action="store_true", required=True)
    value.add_argument("--socket", required=True)
    value.add_argument("--lifetime-seconds", required=True, type=int)
    value.add_argument("--registration-fd", required=True, type=int)
    return value


def main() -> int:
    args = parser().parse_args()
    return _proxy_helper(
        Path(args.socket), args.lifetime_seconds, args.registration_fd,
    )


if __name__ == "__main__":
    raise SystemExit(main())
