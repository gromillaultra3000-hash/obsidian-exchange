"""Fail-closed runtime for one E4 disposable snapshot rehearsal.

The executor is deliberately narrower than a general Docker runner.  It accepts
only an authenticated owner/reviewer gate, one already-consumed replay claim,
an exact runner boundary and a verified encrypted snapshot.  The decryption
identity is supplied as an already-open ephemeral file descriptor; the module
never accepts key bytes or a key path and never creates a key file.

The concrete Docker adapter is intentionally injectable.  Tests use a fake
adapter, while the real adapter uses argv-only subprocess calls, ``network=none``
and a read-only, tmpfs-only, non-root container.  No production DSN, network
route, migration command, persistent volume or automatic retry exists here.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import subprocess
import time
import fcntl
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Iterator, Mapping, Protocol

from core.e4_rehearsal_runner_authorization import (
    validate_authorization_receipt, validate_owner_approval,
)
from core.e4_rehearsal_runner_boundary import (
    POSTGRES_IMAGE, validate_runner_boundary,
)
from core.e4_rehearsal_runner_plan import STEPS, validate_rehearsal_runner_plan
from core.e4_authenticated_gate_provider import (
    AuthenticatedExecutionGateProvider, validate_gate_provider_result,
)

SCHEMA = "e4-hardened-executor.v1"
TARGET_ID = re.compile(r"^[0-9a-f]{12,64}$")
TOKEN = re.compile(r"^[a-z0-9][a-z0-9_-]{0,127}$")
MAX_HEALTH_WAIT_SECONDS = 30.0
MAX_RESTORE_SECONDS = 120.0
MAX_COMMAND_OUTPUT = 4096


class HardenedExecutorError(ValueError):
    """A fail-closed validation or bounded-runtime failure."""


def _hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=True, sort_keys=True,
        separators=(",", ":")).encode()).hexdigest()


def _digest(value: Any, field: str) -> str:
    if not isinstance(value, str) or len(value) != 64 \
            or any(char not in "0123456789abcdef" for char in value):
        raise HardenedExecutorError(f"{field} is invalid")
    return value


def _token(value: Any, field: str) -> str:
    if not isinstance(value, str) or not TOKEN.fullmatch(value):
        raise HardenedExecutorError(f"{field} is invalid")
    return value


def _id(value: Any, prefix: str, field: str) -> str:
    if not isinstance(value, str) or not value.startswith(prefix) \
            or len(value) != len(prefix) + 64 \
            or any(char not in "0123456789abcdef" for char in value[len(prefix):]):
        raise HardenedExecutorError(f"{field} is invalid")
    return value


def _bool(value: Any, field: str, expected: bool) -> None:
    if value is not expected:
        raise HardenedExecutorError(f"{field} is not fail-closed")


def _gate_value(gate: Mapping[str, Any], field: str) -> Any:
    """Read the final evidence shape without accepting a weaker fallback."""
    authority = gate.get("authority")
    if not isinstance(authority, Mapping) or field not in authority:
        raise HardenedExecutorError(f"authenticated gate lacks authority.{field}")
    return authority[field]


def validate_authenticated_execution_gate(
    *, authenticated_evidence: Mapping[str, Any],
    replay_consumption: Mapping[str, Any],
) -> dict[str, Any]:
    """Validate cryptographic/replay facts without granting money authority."""
    if not isinstance(authenticated_evidence, Mapping) \
            or authenticated_evidence.get("status") != "VERIFIED":
        raise HardenedExecutorError("authenticated evidence is not VERIFIED")
    promotion = authenticated_evidence.get("promotion")
    replay = authenticated_evidence.get("replay")
    if not isinstance(promotion, Mapping) or \
            promotion.get("registryStatus") != "AUTHENTICATED_ACTIVE":
        raise HardenedExecutorError("trust registry is not AUTHENTICATED_ACTIVE")
    if not isinstance(replay, Mapping) or replay.get("status") != "CONSUMED" \
            or replay.get("replayClaimAllowed") is not True:
        raise HardenedExecutorError("authenticated replay claim is invalid")
    for field in ("trustRegistryAuthenticated", "trustedClockAttested",
                  "replayRegistryChecked", "replayClaimConsumed"):
        _bool(_gate_value(authenticated_evidence, field),
              f"authority.{field}", True)
    for field in ("executionAuthorized", "productionDatabaseContactAllowed",
                  "productionNetworkAllowed", "productionCredentialsAllowed",
                  "proposalApplicationAllowed", "persistentTargetAllowed",
                  "promotionAllowed", "actionAllowed", "moneyActionAllowed"):
        _bool(_gate_value(authenticated_evidence, field),
              f"authority.{field}", False)
    if _gate_value(authenticated_evidence, "executionEffect") != "NONE":
        raise HardenedExecutorError("authenticated gate has an effect")

    if not isinstance(replay_consumption, Mapping) \
            or replay_consumption.get("status") != "CONSUMED" \
            or replay_consumption.get("rehearsalInvocationAllowed") is not True:
        raise HardenedExecutorError("replay consumption does not allow rehearsal")
    for field in ("moneyActionAllowed", "actionAllowed"):
        _bool(replay_consumption.get(field), f"replay.{field}", False)
    if replay_consumption.get("executionEffect") != "NONE":
        raise HardenedExecutorError("replay consumption has an effect")
    claim_id = _id(replay.get("claimId"), "e4orr_", "replay claim ID")
    consumption_id = _id(
        replay_consumption.get("consumptionId"), "e4rrc_", "replay consumption ID")
    if replay_consumption.get("replayClaimId") != claim_id:
        raise HardenedExecutorError("replay claim is not bound to consumption")
    return {
        "claimId": claim_id,
        "consumptionId": consumption_id,
        "registryStatus": promotion["registryStatus"],
        "trustedClockAttested": True,
    }


@dataclass(frozen=True)
class SnapshotHandle:
    """An open, digest-verified ciphertext descriptor; never plaintext."""

    fd: int
    proc_path: str
    sha256: str
    device: int
    inode: int
    size_bytes: int


@dataclass(frozen=True)
class PlaintextSnapshotHandle:
    """A sealed anonymous, digest-verified plaintext descriptor."""

    fd: int
    sha256: str
    size_bytes: int


class EncryptedSnapshotSource(Protocol):
    @contextmanager
    def open_verified(self, *, expected_sha256: str) -> Iterator[SnapshotHandle]:
        ...


class EphemeralKeySource(Protocol):
    @contextmanager
    def open_key_fd(self) -> Iterator[int]:
        """Yield an external ephemeral FD; never return bytes or a path."""
        ...


class EphemeralPlaintextSource(Protocol):
    @contextmanager
    def open_verified(self, *, expected_sha256: str) \
            -> Iterator[PlaintextSnapshotHandle]:
        """Yield a sealed anonymous plaintext FD after exact digest verification."""
        ...


class RuntimeAdapter(Protocol):
    def target_absent(self, *, target_ref: str) -> bool:
        ...

    def create_target(self, *, target_ref: str, plan_id: str,
                      boundary_id: str, target_fingerprint: str) -> Mapping[str, Any]:
        ...

    def inspect_owned_target(self, *, identity: Mapping[str, Any],
                             target_ref: str, plan_id: str,
                             boundary_id: str, target_fingerprint: str) -> Mapping[str, Any]:
        ...

    def wait_ready(self, *, identity: Mapping[str, Any],
                   timeout_seconds: float) -> None:
        ...

    def restore_snapshot(self, *, identity: Mapping[str, Any],
                         snapshot: SnapshotHandle, key_fd: int,
                         timeout_seconds: float) -> None:
        ...

    def restore_plaintext_snapshot(self, *, identity: Mapping[str, Any],
                                   plaintext: PlaintextSnapshotHandle,
                                   timeout_seconds: float) -> None:
        ...

    def revoke_post_load_writes(self, *, identity: Mapping[str, Any]) -> None:
        ...

    def collect_read_only_evidence(self, *, identity: Mapping[str, Any]) -> Mapping[str, Any]:
        ...

    def destroy_owned_target(self, *, identity: Mapping[str, Any]) -> None:
        ...

    def target_absent_by_identity(self, *, identity: Mapping[str, Any]) -> bool:
        ...


class ImmutableEncryptedSnapshot:
    """Open a staged ciphertext by inode, verify it, and expose only its FD."""

    def __init__(self, *, path: Path, expected_sha256: str, expected_device: int,
                 expected_inode: int, expected_size_bytes: int,
                 expected_hardlink_count: int = 1,
                 expected_parent_device: int | None = None,
                 expected_parent_inode: int | None = None,
                 require_immutable: bool = True):
        self.path = Path(path).absolute()
        self.expected_sha256 = _digest(expected_sha256, "expected_sha256")
        self.expected_device = expected_device
        self.expected_inode = expected_inode
        self.expected_size_bytes = expected_size_bytes
        if isinstance(expected_hardlink_count, bool) or expected_hardlink_count < 1:
            raise HardenedExecutorError("expected hardlink count is invalid")
        self.expected_hardlink_count = expected_hardlink_count
        if (expected_parent_device is None) != (expected_parent_inode is None):
            raise HardenedExecutorError("expected parent handle is incomplete")
        self.expected_parent_device = expected_parent_device
        self.expected_parent_inode = expected_parent_inode
        self.require_immutable = require_immutable

    @staticmethod
    def _immutable_flag(fd: int) -> bool:
        # Linux FS_IOC_GETFLAGS / FS_IMMUTABLE_FL.  Failure is fail-closed.
        try:
            import array
            import fcntl
            flags = array.array("L", [0])
            fcntl.ioctl(fd, 0x80086601, flags, True)
            return bool(flags[0] & 0x00000010)
        except (ImportError, OSError, ValueError):
            return False

    @contextmanager
    def open_verified(self, *, expected_sha256: str) -> Iterator[SnapshotHandle]:
        expected = _digest(expected_sha256, "expected_sha256")
        if expected != self.expected_sha256:
            raise HardenedExecutorError("snapshot digest expectation differs")
        flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        parent_flags = os.O_RDONLY | os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            parent_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            parent_flags |= os.O_NOFOLLOW
        parent_fd: int | None = None
        fd: int | None = None
        try:
            parent_fd = os.open(self.path.parent, parent_flags)
            parent_stat = os.fstat(parent_fd)
            if self.expected_parent_device is not None and (
                    parent_stat.st_dev, parent_stat.st_ino) != (
                        self.expected_parent_device, self.expected_parent_inode):
                raise HardenedExecutorError("snapshot parent handle differs")
            fd = os.open(self.path.name, flags, dir_fd=parent_fd)
        except (OSError, HardenedExecutorError) as exc:
            if fd is not None:
                os.close(fd)
            if parent_fd is not None:
                os.close(parent_fd)
            if isinstance(exc, HardenedExecutorError):
                raise
            raise HardenedExecutorError("snapshot cannot be opened safely") from exc
        try:
            before = os.fstat(fd)
            if (before.st_dev, before.st_ino, before.st_size) != (
                    self.expected_device, self.expected_inode, self.expected_size_bytes):
                raise HardenedExecutorError("snapshot immutable handle differs")
            if not stat.S_ISREG(before.st_mode) \
                    or before.st_nlink != self.expected_hardlink_count:
                raise HardenedExecutorError("snapshot file type or hardlink count differs")
            if self.require_immutable and not self._immutable_flag(fd):
                raise HardenedExecutorError("snapshot immutable flag is absent")
            digest = hashlib.sha256()
            offset = 0
            while offset < before.st_size:
                chunk = os.pread(fd, min(1024 * 1024, before.st_size - offset), offset)
                if not chunk:
                    raise HardenedExecutorError("snapshot ended during digest")
                digest.update(chunk)
                offset += len(chunk)
            after = os.fstat(fd)
            if (after.st_dev, after.st_ino, after.st_size) != (
                    before.st_dev, before.st_ino, before.st_size):
                raise HardenedExecutorError("snapshot changed during digest")
            if digest.hexdigest() != expected:
                raise HardenedExecutorError("snapshot digest mismatch")
            yield SnapshotHandle(
                fd=fd, proc_path=f"/proc/self/fd/{fd}", sha256=expected,
                device=before.st_dev, inode=before.st_ino, size_bytes=before.st_size)
        finally:
            assert fd is not None and parent_fd is not None
            os.close(fd)
            os.close(parent_fd)


class EphemeralFDKeySource:
    """Borrow an already-open key FD without reading, copying or closing it."""

    def __init__(self, fd: int):
        if isinstance(fd, bool) or not isinstance(fd, int) or fd < 3:
            raise HardenedExecutorError("key source must be an external FD")
        self.fd = fd

    @contextmanager
    def open_key_fd(self) -> Iterator[int]:
        try:
            descriptor = os.fstat(self.fd)
        except OSError as exc:
            raise HardenedExecutorError("ephemeral key FD is unavailable") from exc
        if stat.S_ISREG(descriptor.st_mode) and descriptor.st_nlink != 0:
            raise HardenedExecutorError(
                "key FD points to a linked regular file; ephemeral handoff required")
        if not (stat.S_ISREG(descriptor.st_mode) or stat.S_ISFIFO(descriptor.st_mode)):
            raise HardenedExecutorError("key FD type is not an ephemeral stream")
        yield self.fd


class EphemeralFDPlaintextSource:
    """Borrow and reverify a sealed, anonymous plaintext snapshot memfd."""

    def __init__(self, fd: int, *, expected_sha256: str,
                 expected_size_bytes: int):
        if isinstance(fd, bool) or not isinstance(fd, int) or fd < 3:
            raise HardenedExecutorError("plaintext source must be an external FD")
        if isinstance(expected_size_bytes, bool) \
                or not isinstance(expected_size_bytes, int) \
                or expected_size_bytes <= 0:
            raise HardenedExecutorError("plaintext source size is invalid")
        self.fd = fd
        self.expected_sha256 = _digest(expected_sha256, "plaintextSha256")
        self.expected_size_bytes = expected_size_bytes

    @contextmanager
    def open_verified(self, *, expected_sha256: str) \
            -> Iterator[PlaintextSnapshotHandle]:
        expected = _digest(expected_sha256, "plaintextSha256")
        if expected != self.expected_sha256:
            raise HardenedExecutorError("plaintext digest expectation differs")
        try:
            metadata = os.fstat(self.fd)
            if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 0 \
                    or metadata.st_size != self.expected_size_bytes:
                raise HardenedExecutorError(
                    "plaintext FD is not an exact anonymous regular file")
            if not hasattr(fcntl, "F_GET_SEALS"):
                raise HardenedExecutorError("plaintext FD sealing is unavailable")
            seals = fcntl.fcntl(self.fd, fcntl.F_GET_SEALS)
            required = (fcntl.F_SEAL_SEAL | fcntl.F_SEAL_SHRINK |
                        fcntl.F_SEAL_GROW | fcntl.F_SEAL_WRITE)
            if seals & required != required:
                raise HardenedExecutorError("plaintext FD is not fully sealed")
            digest = hashlib.sha256()
            offset = 0
            while offset < metadata.st_size:
                chunk = os.pread(
                    self.fd, min(1024 * 1024, metadata.st_size - offset), offset)
                if not chunk:
                    raise HardenedExecutorError("plaintext FD ended during digest")
                digest.update(chunk)
                offset += len(chunk)
            if digest.hexdigest() != expected:
                raise HardenedExecutorError("plaintext snapshot digest mismatch")
            os.lseek(self.fd, 0, os.SEEK_SET)
            yield PlaintextSnapshotHandle(
                fd=self.fd, sha256=expected, size_bytes=metadata.st_size)
        except OSError as exc:
            raise HardenedExecutorError("plaintext FD is unavailable") from exc


class SubprocessDockerRuntime:
    """Bounded Docker/age adapter with no shell and no inherited environment."""

    def __init__(self, *, docker_bin: str = "/usr/bin/docker",
                 age_bin: str = "/usr/bin/age",
                 sleeper: Callable[[float], None] = time.sleep):
        for value, field in ((docker_bin, "docker_bin"), (age_bin, "age_bin")):
            if not isinstance(value, str) or not value.startswith("/") \
                    or "/" not in value:
                raise HardenedExecutorError(f"{field} must be an absolute path")
        self.docker_bin = docker_bin
        self.age_bin = age_bin
        self.sleeper = sleeper

    @staticmethod
    def _env() -> dict[str, str]:
        return {"PATH": "/usr/bin:/bin", "LC_ALL": "C"}

    def _run(self, argv: list[str], *, timeout: float,
             stdin: Any = subprocess.DEVNULL) -> subprocess.CompletedProcess[str]:
        try:
            return subprocess.run(
                argv, stdin=stdin, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                text=True, env=self._env(), cwd="/", timeout=timeout,
                check=False, shell=False)
        except (OSError, subprocess.SubprocessError) as exc:
            raise HardenedExecutorError("bounded runtime command failed") from exc

    @staticmethod
    def _lines(result: subprocess.CompletedProcess[str]) -> list[str]:
        if result.returncode != 0:
            raise HardenedExecutorError("runtime command returned non-zero")
        return [line.strip() for line in result.stdout.splitlines()
                if line.strip()][:MAX_COMMAND_OUTPUT]

    def target_absent(self, *, target_ref: str) -> bool:
        result = self._run([
            self.docker_bin, "ps", "-aq", "--no-trunc", "--filter",
            f"name=^{target_ref}$"], timeout=5)
        return self._lines(result) == []

    def create_target(self, *, target_ref: str, plan_id: str,
                      boundary_id: str, target_fingerprint: str) -> Mapping[str, Any]:
        for value, field in ((target_ref, "target_ref"), (plan_id, "plan_id"),
                             (boundary_id, "boundary_id"),
                             (target_fingerprint, "target_fingerprint")):
            _token(value, field) if field != "target_fingerprint" \
                else _digest(value, field)
        result = self._run([
            self.docker_bin, "run", "--detach", "--pull=never", "--name", target_ref,
            "--label", f"e4.plan_id={plan_id}",
            "--label", f"e4.boundary_id={boundary_id}",
            "--label", f"e4.target_fingerprint={target_fingerprint}",
            "--network", "none", "--read-only", "--user", "postgres",
            "--tmpfs", "/var/lib/postgresql/data:rw,noexec,nosuid,nodev,size=256m",
            "--tmpfs", "/run/postgresql:rw,noexec,nosuid,nodev,size=16m",
            "--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=32m",
            "--shm-size", "64m", "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges:true", "--pids-limit", "256",
            "--memory", "512m", "--cpus", "1.0", "--restart", "no",
            "--env", "POSTGRES_HOST_AUTH_METHOD=trust", POSTGRES_IMAGE,
        ], timeout=15)
        lines = self._lines(result)
        if len(lines) != 1 or not TARGET_ID.fullmatch(lines[0]):
            raise HardenedExecutorError("runtime returned an invalid container ID")
        return {
            "containerId": lines[0], "targetRef": target_ref,
            "planId": plan_id, "boundaryId": boundary_id,
            "targetFingerprint": target_fingerprint,
            "ownershipToken": _hash({
                "e4.plan_id": plan_id, "e4.boundary_id": boundary_id,
                "e4.target_fingerprint": target_fingerprint,
            }),
        }

    def _inspect(self, *, container_id: str) -> Mapping[str, Any]:
        if not TARGET_ID.fullmatch(container_id):
            raise HardenedExecutorError("container identity is invalid")
        result = self._run([self.docker_bin, "inspect", container_id], timeout=5)
        lines = self._lines(result)
        try:
            value = json.loads("\n".join(lines))
        except json.JSONDecodeError as exc:
            raise HardenedExecutorError("container inspect is not JSON") from exc
        if not isinstance(value, list) or len(value) != 1 \
                or not isinstance(value[0], Mapping):
            raise HardenedExecutorError("container inspect shape is invalid")
        return value[0]

    def inspect_owned_target(self, *, identity: Mapping[str, Any], target_ref: str,
                             plan_id: str, boundary_id: str,
                             target_fingerprint: str) -> Mapping[str, Any]:
        container_id = identity.get("containerId")
        if not isinstance(container_id, str):
            raise HardenedExecutorError("container identity is missing")
        value = self._inspect(container_id=container_id)
        config = value.get("Config")
        host = value.get("HostConfig")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        if not isinstance(config, Mapping) or not isinstance(host, Mapping) \
                or not isinstance(labels, Mapping):
            raise HardenedExecutorError("container inspect lacks hardened fields")
        required_labels = {
            "e4.plan_id": plan_id, "e4.boundary_id": boundary_id,
            "e4.target_fingerprint": target_fingerprint,
        }
        if value.get("Name") != f"/{target_ref}" \
                or config.get("Image") != POSTGRES_IMAGE \
                or config.get("User") != "postgres" \
                or any(labels.get(key) != item for key, item in required_labels.items()):
            raise HardenedExecutorError("container ownership or image binding differs")
        if host.get("NetworkMode") != "none" or host.get("ReadonlyRootfs") is not True \
                or host.get("Binds") not in (None, []) \
                or host.get("PortBindings") not in (None, {}) \
                or host.get("Privileged") is True \
                or "ALL" not in (host.get("CapDrop") or []) \
                or "no-new-privileges:true" not in (host.get("SecurityOpt") or []):
            raise HardenedExecutorError("container hardening differs")
        mounts = host.get("Mounts") or value.get("Mounts") or []
        if any(isinstance(item, Mapping) and item.get("Type") != "tmpfs"
               for item in mounts):
            raise HardenedExecutorError("host-backed mount detected")
        state = value.get("State")
        if not isinstance(state, Mapping) or state.get("Running") is not True:
            raise HardenedExecutorError("container is not running")
        expected_token = _hash(required_labels)
        if identity.get("ownershipToken", expected_token) != expected_token:
            raise HardenedExecutorError("container ownership token differs")
        return {"containerId": container_id, "targetRef": target_ref,
                "planId": plan_id, "boundaryId": boundary_id,
                "targetFingerprint": target_fingerprint,
                "ownershipToken": expected_token,
                "containerIdentityCaptured": True}

    def _exec(self, *, identity: Mapping[str, Any], argv: list[str],
              timeout: float) -> subprocess.CompletedProcess[str]:
        container_id = identity.get("containerId")
        if not isinstance(container_id, str) or not TARGET_ID.fullmatch(container_id):
            raise HardenedExecutorError("container identity is invalid")
        return self._run([self.docker_bin, "exec", "--user", "postgres",
                          container_id, *argv], timeout=timeout)

    def wait_ready(self, *, identity: Mapping[str, Any],
                   timeout_seconds: float) -> None:
        deadline = time.monotonic() + min(timeout_seconds, MAX_HEALTH_WAIT_SECONDS)
        while time.monotonic() < deadline:
            result = self._exec(
                identity=identity,
                argv=["pg_isready", "--quiet", "--dbname=postgres",
                      "--host=/var/run/postgresql"], timeout=2)
            if result.returncode == 0:
                return
            self.sleeper(0.25)
        raise HardenedExecutorError("bounded PostgreSQL health check expired")

    def restore_snapshot(self, *, identity: Mapping[str, Any],
                         snapshot: SnapshotHandle, key_fd: int,
                         timeout_seconds: float) -> None:
        if not isinstance(key_fd, int) or key_fd < 3:
            raise HardenedExecutorError("restore requires an ephemeral key FD")
        try:
            os.fstat(key_fd)
            os.fstat(snapshot.fd)
        except OSError as exc:
            raise HardenedExecutorError("restore FD is unavailable") from exc
        age = restore = None
        try:
            age = subprocess.Popen(
                [self.age_bin, "--decrypt", "--identity", f"/proc/self/fd/{key_fd}",
                 snapshot.proc_path], stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=self._env(), cwd="/", close_fds=True,
                pass_fds=(key_fd, snapshot.fd), shell=False)
            assert age.stdout is not None
            restore = subprocess.Popen(
                [self.docker_bin, "exec", "--interactive", "--user", "postgres",
                 identity["containerId"], "pg_restore", "--dbname=postgres",
                 "--no-owner", "--no-privileges", "--exit-on-error",
                 "--single-transaction"], stdin=age.stdout,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=self._env(), cwd="/", close_fds=True, shell=False)
            age.stdout.close()
            restore.wait(timeout=min(timeout_seconds, MAX_RESTORE_SECONDS))
            age.wait(timeout=5)
            if restore.returncode != 0 or age.returncode != 0:
                raise HardenedExecutorError("encrypted snapshot restore failed")
        except (OSError, subprocess.SubprocessError) as exc:
            raise HardenedExecutorError("encrypted snapshot restore was ambiguous") from exc
        finally:
            for process in (restore, age):
                if process is not None and process.poll() is None:
                    process.kill()
            for process in (restore, age):
                if process is not None:
                    try:
                        process.wait(timeout=2)
                    except subprocess.SubprocessError:
                        pass

    def restore_plaintext_snapshot(self, *, identity: Mapping[str, Any],
                                   plaintext: PlaintextSnapshotHandle,
                                   timeout_seconds: float) -> None:
        if not isinstance(plaintext, PlaintextSnapshotHandle):
            raise HardenedExecutorError("verified plaintext handle is required")
        try:
            os.fstat(plaintext.fd)
            os.lseek(plaintext.fd, 0, os.SEEK_SET)
            restore = subprocess.Popen(
                [self.docker_bin, "exec", "--interactive", "--user", "postgres",
                 identity["containerId"], "pg_restore", "--dbname=postgres",
                 "--no-owner", "--no-privileges", "--exit-on-error",
                 "--single-transaction"], stdin=plaintext.fd,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                env=self._env(), cwd="/", close_fds=True, shell=False)
            restore.wait(timeout=min(timeout_seconds, MAX_RESTORE_SECONDS))
            if restore.returncode != 0:
                raise HardenedExecutorError("plaintext snapshot restore failed")
        except (OSError, subprocess.SubprocessError) as exc:
            raise HardenedExecutorError(
                "plaintext snapshot restore was ambiguous") from exc
        finally:
            if "restore" in locals() and restore.poll() is None:
                restore.kill()
            if "restore" in locals():
                try:
                    restore.wait(timeout=2)
                except subprocess.SubprocessError:
                    pass

    def revoke_post_load_writes(self, *, identity: Mapping[str, Any]) -> None:
        result = self._exec(
            identity=identity,
            argv=["psql", "-X", "-v", "ON_ERROR_STOP=1", "--dbname=postgres",
                  "--command=REVOKE CREATE ON SCHEMA public FROM PUBLIC;"
                  " REVOKE ALL ON DATABASE postgres FROM PUBLIC;"], timeout=10)
        if result.returncode != 0:
            raise HardenedExecutorError("post-load write capability was not revoked")

    def collect_read_only_evidence(self, *, identity: Mapping[str, Any]) -> Mapping[str, Any]:
        queries = {
            "tables": "SELECT schemaname,tablename FROM pg_catalog.pg_tables ORDER BY 1,2;",
            "acls": "SELECT n.nspname,c.relname,pg_catalog.array_to_string(c.relacl,',') "
                    "FROM pg_catalog.pg_class c JOIN pg_catalog.pg_namespace n "
                    "ON n.oid=c.relnamespace WHERE c.relkind IN ('r','p','v') ORDER BY 1,2;",
            "proposal_absent": "SELECT to_regclass('public.e4_action_reservations') IS NULL "
                               "AND to_regprocedure('public.e4_guard_action_reservation_mutation()') IS NULL;",
        }
        result: dict[str, Any] = {}
        for name, query in queries.items():
            output = self._exec(identity=identity, argv=[
                "psql", "-X", "--tuples-only", "--no-align", "--dbname=postgres",
                f"--command={query}"], timeout=10)
            if output.returncode != 0:
                raise HardenedExecutorError("read-only evidence query failed")
            text = output.stdout[:MAX_COMMAND_OUTPUT]
            result[f"{name}Sha256"] = hashlib.sha256(text.encode()).hexdigest()
            if name == "proposal_absent" and text.strip().lower() != "t":
                raise HardenedExecutorError("proposal migration is present")
        result["secretFree"] = True
        result["productionContacted"] = False
        result["writesPerformed"] = False
        return result

    def destroy_owned_target(self, *, identity: Mapping[str, Any]) -> None:
        container_id = identity.get("containerId")
        if not isinstance(container_id, str) or not TARGET_ID.fullmatch(container_id):
            raise HardenedExecutorError("container identity is invalid")
        target_ref = identity.get("targetRef")
        plan_id = identity.get("planId")
        boundary_id = identity.get("boundaryId")
        target_fingerprint = identity.get("targetFingerprint")
        ownership_token = identity.get("ownershipToken")
        if not isinstance(target_ref, str) or not isinstance(plan_id, str) \
                or not isinstance(boundary_id, str) \
                or not isinstance(target_fingerprint, str) \
                or not isinstance(ownership_token, str):
            raise HardenedExecutorError("owned target proof is incomplete")
        value = self._inspect(container_id=container_id)
        config = value.get("Config")
        labels = config.get("Labels") if isinstance(config, Mapping) else None
        expected = {
            "e4.plan_id": plan_id, "e4.boundary_id": boundary_id,
            "e4.target_fingerprint": target_fingerprint,
        }
        if value.get("Name") != f"/{target_ref}" \
                or not isinstance(config, Mapping) \
                or config.get("Image") != POSTGRES_IMAGE \
                or not isinstance(labels, Mapping) \
                or any(labels.get(key) != item for key, item in expected.items()) \
                or ownership_token != _hash(expected):
            raise HardenedExecutorError("refusing to destroy an unowned target")
        result = self._run([self.docker_bin, "rm", "--force", container_id], timeout=15)
        if result.returncode != 0:
            raise HardenedExecutorError("owned target teardown failed")

    def target_absent_by_identity(self, *, identity: Mapping[str, Any]) -> bool:
        container_id = identity.get("containerId")
        if not isinstance(container_id, str) or not TARGET_ID.fullmatch(container_id):
            raise HardenedExecutorError("container identity is invalid")
        result = self._run([self.docker_bin, "ps", "-aq", "--no-trunc",
                            "--filter", f"id={container_id}"], timeout=5)
        return self._lines(result) == []


class HardenedE4Executor:
    """Execute one isolated fixture rehearsal and emit secret-free evidence."""

    def __init__(self, *, runtime: RuntimeAdapter,
                 clock: Callable[[], int] | None = None):
        self.runtime = runtime
        self.clock = clock or (lambda: int(time.time() * 1000))

    def execute(self, *, plan: Mapping[str, Any], receipt: Mapping[str, Any],
                owner_approval: Mapping[str, Any], boundary: Mapping[str, Any],
                gate_provider: AuthenticatedExecutionGateProvider,
                snapshot_ref: str, key_ref: str,
                snapshot_source: EncryptedSnapshotSource,
                key_source: EphemeralKeySource | None = None,
                plaintext_source: EphemeralPlaintextSource | None = None,
                expected_plaintext_sha256: str | None = None) -> dict[str, Any]:
        frozen_plan = validate_rehearsal_runner_plan(plan)
        frozen_receipt = validate_authorization_receipt(receipt)
        frozen_approval = validate_owner_approval(owner_approval)
        plaintext_mode = plaintext_source is not None
        if plaintext_mode == (key_source is not None):
            raise HardenedExecutorError(
                "exactly one decryption-key or predecrypted source is required")
        plaintext_digest = None
        if plaintext_mode:
            plaintext_digest = _digest(
                expected_plaintext_sha256, "expectedPlaintextSha256")
            if not hasattr(self.runtime, "restore_plaintext_snapshot"):
                raise HardenedExecutorError(
                    "runtime lacks a predecrypted restore boundary")
        if frozen_receipt["status"] != "ELIGIBLE" \
                or frozen_receipt["rehearsalExecutionEligible"] is not True:
            raise HardenedExecutorError("receipt is not eligible")
        if frozen_approval["approvalId"] != frozen_receipt["approvalId"]:
            raise HardenedExecutorError("approval/receipt binding differs")
        frozen_boundary = validate_runner_boundary(
            boundary, plan=frozen_plan, receipt=frozen_receipt,
            snapshot_ref=snapshot_ref, key_ref=key_ref)
        if not hasattr(gate_provider, "acquire"):
            raise HardenedExecutorError("authoritative gate provider is required")
        try:
            provider_result = gate_provider.acquire(
                plan=frozen_plan, receipt=frozen_receipt,
                owner_approval=frozen_approval, boundary=frozen_boundary,
                snapshot_ref=snapshot_ref, key_ref=key_ref,
                evaluated_at_epoch_ms=self.clock())
            provider_result = validate_gate_provider_result(
                provider_result, plan=frozen_plan, receipt=frozen_receipt,
                boundary=frozen_boundary, snapshot_ref=snapshot_ref, key_ref=key_ref)
        except (TypeError, ValueError) as exc:
            raise HardenedExecutorError("authoritative gate provider failed") from exc
        authenticated_evidence = provider_result["authenticatedEvidence"]
        replay_consumption = provider_result["replayConsumption"]
        gate = validate_authenticated_execution_gate(
            authenticated_evidence=authenticated_evidence,
            replay_consumption=replay_consumption)
        for field, expected in (
                ("planId", frozen_plan["planId"]),
                ("targetRef", frozen_receipt["targetRef"]),
                ("snapshotSha256", frozen_receipt["snapshotSha256"]),
                ("boundaryId", frozen_boundary["boundaryId"])):
            if replay_consumption.get(field) != expected:
                raise HardenedExecutorError(
                    f"replay consumption {field} is not receipt-bound")
        target = frozen_receipt["targetRef"]
        target_fingerprint = frozen_receipt["targetFingerprintSha256"]
        if frozen_boundary["target"]["targetRef"] != target:
            raise HardenedExecutorError("target binding differs")
        if not self.runtime.target_absent(target_ref=target):
            raise HardenedExecutorError("target was not absent before start")

        identity: Mapping[str, Any] | None = None
        teardown_ok = False
        steps: list[dict[str, Any]] = []
        evidence: Mapping[str, Any] | None = None
        try:
            steps.append({"stepId": "VERIFY_TARGET_ABSENT", "evidenceCaptured": True})
            with snapshot_source.open_verified(expected_sha256=frozen_receipt["snapshotSha256"]) as snapshot:
                steps.append({"stepId": "VERIFY_MANIFEST_AND_SNAPSHOT_DIGESTS",
                              "evidenceCaptured": True})
                identity = self.runtime.create_target(
                    target_ref=target, plan_id=frozen_plan["planId"],
                    boundary_id=frozen_boundary["boundaryId"],
                    target_fingerprint=target_fingerprint)
                if not isinstance(identity, Mapping) \
                        or identity.get("targetRef") != target \
                        or not isinstance(identity.get("containerId"), str):
                    raise HardenedExecutorError("runtime returned an unbound target")
                owned = self.runtime.inspect_owned_target(
                    identity=identity, target_ref=target, plan_id=frozen_plan["planId"],
                    boundary_id=frozen_boundary["boundaryId"],
                    target_fingerprint=target_fingerprint)
                if not isinstance(owned, Mapping) \
                        or owned.get("targetRef") != target \
                        or owned.get("containerIdentityCaptured") is not True:
                    raise HardenedExecutorError("runtime did not capture target identity")
                identity = dict(owned)
                steps.append({"stepId": "CREATE_DISPOSABLE_POSTGRESQL_TARGET",
                              "evidenceCaptured": True})
                self.runtime.wait_ready(identity=identity,
                                        timeout_seconds=MAX_HEALTH_WAIT_SECONDS)
                if plaintext_mode:
                    assert plaintext_source is not None \
                        and plaintext_digest is not None
                    with plaintext_source.open_verified(
                            expected_sha256=plaintext_digest) as plaintext:
                        self.runtime.restore_plaintext_snapshot(
                            identity=identity, plaintext=plaintext,
                            timeout_seconds=MAX_RESTORE_SECONDS)
                else:
                    assert key_source is not None
                    with key_source.open_key_fd() as key_fd:
                        self.runtime.restore_snapshot(
                            identity=identity, snapshot=snapshot, key_fd=key_fd,
                            timeout_seconds=MAX_RESTORE_SECONDS)
                steps.append({"stepId": "LOAD_SNAPSHOT_INTO_DISPOSABLE_TARGET",
                              "evidenceCaptured": True})
                self.runtime.revoke_post_load_writes(identity=identity)
                steps.append({"stepId": "REVOKE_POST_LOAD_WRITE_CAPABILITY",
                              "evidenceCaptured": True})
                evidence = self.runtime.collect_read_only_evidence(identity=identity)
                for step, _effect in STEPS[5:10]:
                    steps.append({"stepId": step, "evidenceCaptured": True})
        finally:
            if identity is not None:
                self.runtime.destroy_owned_target(identity=identity)
                teardown_ok = self.runtime.target_absent_by_identity(identity=identity)
                if not teardown_ok:
                    raise HardenedExecutorError("target absence was not proven")
        if not teardown_ok or evidence is None:
            raise HardenedExecutorError("rehearsal did not reach teardown proof")
        steps.extend([
            {"stepId": "DESTROY_DISPOSABLE_TARGET_AND_STAGED_SNAPSHOT",
             "evidenceCaptured": True},
            {"stepId": "VERIFY_TARGET_AND_SNAPSHOT_ABSENT", "evidenceCaptured": True},
        ])
        if [item["stepId"] for item in steps] != [step for step, _ in STEPS]:
            raise HardenedExecutorError("executor step sequence is incomplete")
        now = self.clock()
        result = {
            "schemaVersion": SCHEMA,
            "status": "NON_PRODUCTION_REHEARSAL_SOURCE_RETENTION_REVIEW",
            "executionId": "e4hex_" + _hash({
                "planId": frozen_plan["planId"], "consumptionId": gate["consumptionId"],
                "target": target, "evaluatedAtEpochMs": now}),
            "planId": frozen_plan["planId"],
            "consumptionId": gate["consumptionId"],
            "replayClaimId": gate["claimId"],
            "evaluatedAtEpochMs": now,
            "target": {
                "targetRef": target, "targetFingerprintSha256": target_fingerprint,
                "absentBeforeStart": True, "ownershipTokenCaptured": True,
                "containerIdentityCaptured": True, "targetNameImmutable": True,
            },
            "container": {
                "image": POSTGRES_IMAGE, "network": "none", "readOnlyRoot": True,
                "publishedPorts": [], "persistentVolume": False, "tmpfsOnly": True,
                "noNewPrivileges": True, "dropAllCapabilities": True, "nonRoot": True,
                "boundedHealthcheck": True, "boundedShutdown": True, "noHostPath": True,
            },
            "snapshot": {
                "preExisting": True, "encrypted": True, "immutableAtHandoff": True,
                "digestVerified": True, "plaintextPersistenceNone": True,
                "productionDisconnected": True, "absentAfterTeardown": True,
                "sourceCiphertextRetained": True,
                "decryptionLocation": (
                    "CLIENT_TERMUX" if plaintext_mode else "SERVER_EPHEMERAL_FD"),
                "decryptionKeyReceivedByServer": not plaintext_mode,
                "plaintextStreamDigestVerified": plaintext_mode,
                "plaintextSha256": plaintext_digest,
            },
            "readOnlyEvidence": dict(evidence),
            "teardown": {
                "targetDestroyed": True, "targetAbsentAfter": True,
                "snapshotDestroyed": False, "snapshotAbsentAfter": True,
                "transientSnapshotArtifactAbsentAfter": True,
                "ownershipReleased": True, "cleanupEvidenceCaptured": True,
            },
            "steps": [
                {"sequence": index, "stepId": step, "effect": effect,
                 "completed": step not in {
                     "DESTROY_DISPOSABLE_TARGET_AND_STAGED_SNAPSHOT",
                     "VERIFY_TARGET_AND_SNAPSHOT_ABSENT",
                 },
                 "evidenceCaptured": True}
                for index, (step, effect) in enumerate(STEPS, start=1)
            ],
            "production": {
                "contacted": False, "credentialsPresent": False,
                "writesPerformed": False, "networkRouteAllowed": False,
            },
            "authority": {
                "executionAuthorized": False,
                "productionDatabaseContactAllowed": False,
                "productionNetworkAllowed": False,
                "productionCredentialsAllowed": False,
                "proposalApplicationAllowed": False,
                "persistentTargetAllowed": False,
                "automaticRetryAllowed": False,
                "promotionAllowed": False, "actionAllowed": False,
                "moneyActionAllowed": False, "executionEffect": "NONE",
            },
        }
        result["resultSha256"] = _hash(result)
        return result
