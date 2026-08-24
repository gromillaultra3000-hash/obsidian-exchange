"""Superseded E4 handoff retained only to fail closed.

This legacy flow streamed decrypted private-key bytes to the remote process.
It must never be used; the key stays local in the replacement design.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path


KEY = Path.home() / "e4-key" / "owner-ssh"
PUBLIC = Path.home() / "e4-key" / "owner-ssh.pub"
REMOTE = "root@185.236.228.19"
REMOTE_COMMAND = (
    "PYTHONPATH=/root/relay /usr/bin/python3 "
    "-m core.e4_owner_rehearsal_execute"
)
MAX_KEY_BYTES = 16 * 1024


def public_line(path: Path) -> str:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()
             if line.strip()]
    if len(lines) != 1 or not lines[0].startswith("ssh-ed25519 "):
        raise ValueError("owner-ssh.pub is invalid")
    return " ".join(lines[0].split()[:2])


def main() -> int:
    raise ValueError(
        "superseded unsafe handoff: private key transfer is prohibited")
    for command in ("ssh-keygen", "ssh"):
        if shutil.which(command) is None:
            raise ValueError(f"{command} is unavailable")
    metadata = os.lstat(KEY)
    if not stat.S_ISREG(metadata.st_mode) or metadata.st_size <= 0 \
            or metadata.st_size > MAX_KEY_BYTES or metadata.st_uid != os.getuid() \
            or metadata.st_mode & 0o077:
        raise ValueError("owner-ssh file shape or permissions are unsafe")
    source_fd = os.open(KEY, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    flags = getattr(os, "MFD_CLOEXEC", 0) | getattr(os, "MFD_ALLOW_SEALING", 0)
    key_fd = os.memfd_create("e4-owner-ssh-unlock", flags)
    os.fchmod(key_fd, 0o600)
    try:
        remaining = metadata.st_size
        while remaining:
            chunk = os.read(source_fd, min(remaining, 4096))
            if not chunk:
                raise ValueError("owner-ssh ended early")
            os.write(key_fd, chunk)
            remaining -= len(chunk)
        path = f"/proc/{os.getpid()}/fd/{key_fd}"
        print("Введите passphrase ключа owner-ssh. Она остаётся в Termux.")
        unlocked = subprocess.run([
            "ssh-keygen", "-p", "-q", "-N", "", "-f", path,
        ], pass_fds=(key_fd,), check=False)
        if unlocked.returncode != 0:
            raise ValueError("owner-ssh memfd unlock failed")
        os.lseek(key_fd, 0, os.SEEK_SET)
        derived = subprocess.run([
            "ssh-keygen", "-y", "-P", "", "-f", path,
        ], pass_fds=(key_fd,), stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL, check=False)
        if derived.returncode != 0 \
                or derived.stdout.decode().strip() != public_line(PUBLIC):
            raise ValueError("unlocked key does not match owner-ssh.pub")
        os.lseek(key_fd, 0, os.SEEK_SET)
        print("Ключ проверен в memfd. Введите SSH-пароль сервера.")
        completed = subprocess.run([
            "ssh", "-T", "-o", "StrictHostKeyChecking=yes",
            "-o", "HostKeyAlgorithms=ssh-ed25519",
            REMOTE, REMOTE_COMMAND,
        ], stdin=key_fd, check=False)
        return completed.returncode
    finally:
        os.close(source_fd)
        os.close(key_fd)


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"HANDOFF_FAILED: {exc}", file=sys.stderr)
        raise SystemExit(1)
