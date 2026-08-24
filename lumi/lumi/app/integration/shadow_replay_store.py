"""Atomic file adapter for the frozen shadow replay-ledger contract."""

from __future__ import annotations

import fcntl
import json
import os
import stat
import tempfile
import time
from pathlib import Path
from typing import Any, Callable

from lumi.app.integration.shadow_replay_ledger import consume, empty_snapshot, validate_snapshot

MAX_STATE_BYTES = 1024 * 1024


class AtomicReplayStore:
    def __init__(
        self, path: Path, *, capacity: int = 10000,
        clock: Callable[[], int] | None = None,
        fault: Callable[[str], None] | None = None,
    ):
        self.path = Path(path)
        self.capacity = empty_snapshot(capacity=capacity)["capacity"]
        self.clock = clock or (lambda: int(time.time()))
        self.fault = fault or (lambda stage: None)

    def _prepare_parent(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        info = self.path.parent.lstat()
        if not stat.S_ISDIR(info.st_mode) or stat.S_ISLNK(info.st_mode):
            raise ValueError("shadow replay parent directory is invalid")

    def _lock(self) -> int:
        self._prepare_parent()
        lock_path = self.path.with_suffix(self.path.suffix + ".lock")
        flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(lock_path, flags, 0o600)
        except OSError as exc:
            raise ValueError("shadow replay lock is invalid") from exc
        if not stat.S_ISREG(os.fstat(fd).st_mode):
            os.close(fd)
            raise ValueError("shadow replay lock is invalid")
        os.fchmod(fd, 0o600)
        fcntl.flock(fd, fcntl.LOCK_EX)
        return fd

    @staticmethod
    def _unlock(fd: int) -> None:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)

    def _read_locked(self) -> dict[str, Any]:
        try:
            path_info = self.path.lstat()
        except FileNotFoundError:
            return empty_snapshot(capacity=self.capacity)
        if not stat.S_ISREG(path_info.st_mode) or stat.S_ISLNK(path_info.st_mode):
            raise ValueError("shadow replay state is invalid")
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            fd = os.open(self.path, flags)
        except OSError as exc:
            raise ValueError("shadow replay state is invalid") from exc
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_STATE_BYTES \
                    or info.st_mode & 0o077:
                raise ValueError("shadow replay state is invalid")
            raw = os.read(fd, MAX_STATE_BYTES + 1)
        finally:
            os.close(fd)
        try:
            value = json.loads(raw)
        except Exception as exc:
            raise ValueError("shadow replay state is unreadable") from exc
        snapshot = validate_snapshot(value)
        if snapshot["capacity"] != self.capacity:
            raise ValueError("shadow replay state capacity differs")
        return snapshot

    def _write_locked(self, snapshot: dict[str, Any]) -> None:
        raw = json.dumps(
            validate_snapshot(snapshot), sort_keys=True, separators=(",", ":"),
            ensure_ascii=True).encode("utf-8")
        if len(raw) > MAX_STATE_BYTES:
            raise ValueError("shadow replay state is too large")
        fd, raw_path = tempfile.mkstemp(
            prefix=f".{self.path.name}.tmp.", dir=self.path.parent)
        temporary = Path(raw_path)
        try:
            os.fchmod(fd, 0o600)
            written = 0
            while written < len(raw):
                count = os.write(fd, raw[written:])
                if count <= 0:
                    raise ValueError("shadow replay state write failed")
                written += count
            os.fsync(fd)
            os.close(fd)
            fd = -1
            self.fault("after_temp_fsync")
            os.replace(temporary, self.path)
            self.fault("after_replace")
            directory_fd = os.open(self.path.parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        finally:
            if fd >= 0:
                os.close(fd)
            if temporary.exists():
                temporary.unlink()

    def consume(self, key_id: str, nonce: str, expires_at: int) -> dict[str, Any]:
        lock_fd = self._lock()
        try:
            transition = consume(
                self._read_locked(), key_id=key_id, nonce=nonce,
                now_epoch=self.clock(), expires_at=expires_at)
            self._write_locked(transition["nextSnapshot"])
            return transition
        finally:
            self._unlock(lock_fd)

    def snapshot(self) -> dict[str, Any]:
        lock_fd = self._lock()
        try:
            return self._read_locked()
        finally:
            self._unlock(lock_fd)
