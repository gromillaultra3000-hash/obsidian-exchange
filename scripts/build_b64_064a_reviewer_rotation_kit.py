#!/usr/bin/env python3
"""Build a deterministic secret-free 064A reviewer-key rotation kit."""
from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import stat
import sys
import tarfile
from pathlib import Path
from typing import Mapping


ROUTE = "E0/E0.3/B5.3/064A"
SCHEMA = "b64-064a-reviewer-key-rotation-kit.v1"
RELEASE_BASE = Path(
    "/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a"
)
FILES = (
    "deploy/postgres/b64_064a_hardened_refresh.py",
    "deploy/postgres/b64_dump_restore_supervisor.py",
    "scripts/b64_064a_evidence_acceptance.py",
)
OLD_REVIEWER_ACTIVATION_KEY_ID = (
    "b64a_75414a6b14130da8cc9a993fa588f04a0bbbcdaa08c37c32cfbcaa0dcb2d2dd1"
)
OLD_REVIEWER_EVIDENCE_KEY_ID = (
    "b64e_a617c7896122b17b706ad8a40d3c26ca794b36b0a1c01730ffbe4ba4e64a4dbb"
)
NEW_IDENTITY_ID = "reviewer_independent_2026_r2"
NEW_TRUST_DOMAIN = "reviewer_device_02"
MAX_FILE_BYTES = 1024 * 1024
MAX_ARCHIVE_BYTES = 2 * 1024 * 1024


class RotationKitError(RuntimeError):
    """Closed failure reason suitable for a secret-free receipt."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=True, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _release_root() -> Path:
    script = Path(__file__).resolve()
    try:
        release = script.parents[1]
    except IndexError as exc:
        raise RotationKitError(
            "ROTATION_BUILDER_IMMUTABLE_RELEASE_REQUIRED"
        ) from exc
    try:
        release_info = os.lstat(release)
        script_info = os.lstat(script)
    except OSError as exc:
        raise RotationKitError(
            "ROTATION_BUILDER_IMMUTABLE_RELEASE_REQUIRED"
        ) from exc
    if (release.parent != RELEASE_BASE
            or re.fullmatch(r"[0-9a-f]{40}", release.name) is None
            or not stat.S_ISDIR(release_info.st_mode)
            or release_info.st_uid != 0 or release_info.st_gid != 0
            or stat.S_IMODE(release_info.st_mode) != 0o555
            or not stat.S_ISREG(script_info.st_mode)
            or script_info.st_uid != 0 or script_info.st_gid != 0
            or stat.S_IMODE(script_info.st_mode) & 0o022
            or script_info.st_nlink != 1):
        raise RotationKitError(
            "ROTATION_BUILDER_IMMUTABLE_RELEASE_REQUIRED"
        )
    return release


def _source_files(root: Path) -> dict[str, bytes]:
    result: dict[str, bytes] = {}
    for name in FILES:
        path = root / name
        descriptor = -1
        try:
            descriptor = os.open(
                path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
            )
            info = os.fstat(descriptor)
            chunks: list[bytes] = []
            remaining = MAX_FILE_BYTES + 1
            while remaining:
                chunk = os.read(descriptor, remaining)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            raw = b"".join(chunks)
        except OSError as exc:
            raise RotationKitError("ROTATION_SOURCE_UNSAFE") from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != 0 or info.st_gid != 0
                or stat.S_IMODE(info.st_mode) & 0o022
                or info.st_nlink != 1
                or not 1 <= len(raw) <= MAX_FILE_BYTES
                or len(raw) != info.st_size):
            raise RotationKitError("ROTATION_SOURCE_UNSAFE")
        result[name] = raw
    return result


def _readme() -> bytes:
    return (
        "OBSIDIAN 064A REVIEWER KEY ROTATION KIT V1\n"
        "Use only on a genuinely separate controlled reviewer device.\n"
        "Do not copy any existing owner or reviewer private key to this device.\n"
        "Extract into a new mode-0700 directory and verify SHA256SUMS.\n"
        "Create the private output directory with: mkdir -m 700 reviewer-r2\n"
        "Then run:\n"
        "python scripts/b64_064a_evidence_acceptance.py generate-key \\\n"
        "  --role INDEPENDENT_REVIEWER \\\n"
        f"  --identity-id {NEW_IDENTITY_ID} \\\n"
        f"  --trust-domain {NEW_TRUST_DOMAIN} \\\n"
        "  --private-out \"$PWD/reviewer-r2/reviewer.key\" \\\n"
        "  --public-out \"$PWD/reviewer-r2/reviewer-public.json\"\n"
        "The passphrase must be entered only in the hidden local prompt.\n"
        "Return only reviewer-public.json and its SHA-256.\n"
        "Never return reviewer.key, its passphrase, or key-generation output "
        "containing the private-file digest.\n"
    ).encode("utf-8")


def _sha256sums(files: Mapping[str, bytes]) -> bytes:
    return "".join(
        f"{_sha(raw)}  {name}\n" for name, raw in sorted(files.items())
    ).encode("ascii")


def build_archive(
    source_files: Mapping[str, bytes], *, implementation_commit: str,
) -> bytes:
    if (re.fullmatch(r"[0-9a-f]{40}", implementation_commit) is None
            or set(source_files) != set(FILES)):
        raise RotationKitError("ROTATION_SOURCE_SET_INVALID")
    files = dict(source_files)
    files["README.txt"] = _readme()
    manifest_unsigned = {
        "schemaVersion": SCHEMA,
        "route": ROUTE,
        "implementationCommit": implementation_commit,
        "purpose": "ROTATE_CO_RESIDENT_REVIEWER_KEY",
        "oldReviewerActivationKeyId": OLD_REVIEWER_ACTIVATION_KEY_ID,
        "oldReviewerEvidenceKeyId": OLD_REVIEWER_EVIDENCE_KEY_ID,
        "newIdentityId": NEW_IDENTITY_ID,
        "newTrustDomain": NEW_TRUST_DOMAIN,
        "filesSha256": {
            name: _sha(raw) for name, raw in sorted(files.items())
        },
        "containsPrivateKey": False,
        "containsPassphrase": False,
        "containsCredential": False,
        "containsRuntimeRequest": False,
        "productionAuthorityComplete": False,
    }
    manifest = {
        **manifest_unsigned,
        "manifestSha256": _sha(_canonical(manifest_unsigned)),
    }
    files["ROTATION-MANIFEST.json"] = _canonical(manifest) + b"\n"
    files["SHA256SUMS"] = _sha256sums(files)
    output = io.BytesIO()
    with tarfile.open(
        fileobj=output, mode="w", format=tarfile.PAX_FORMAT,
    ) as archive:
        for name in sorted(files):
            raw = files[name]
            info = tarfile.TarInfo(name)
            info.size = len(raw)
            info.mode = 0o600
            info.uid = 0
            info.gid = 0
            info.mtime = 0
            info.uname = "root"
            info.gname = "root"
            archive.addfile(info, io.BytesIO(raw))
    value = output.getvalue()
    if not 1 <= len(value) <= MAX_ARCHIVE_BYTES:
        raise RotationKitError("ROTATION_ARCHIVE_SIZE_INVALID")
    return value


def _write_new(path_text: str, raw: bytes) -> str:
    path = Path(path_text)
    if not path.is_absolute() or re.fullmatch(
        r"[A-Za-z0-9_.-]+", path.name,
    ) is None:
        raise RotationKitError("ROTATION_OUTPUT_UNSAFE")
    try:
        parent_fd = os.open(
            path.parent, os.O_RDONLY | os.O_DIRECTORY
            | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0),
        )
        parent = os.fstat(parent_fd)
    except OSError as exc:
        raise RotationKitError("ROTATION_OUTPUT_UNSAFE") from exc
    descriptor = -1
    created = False
    try:
        if (parent.st_uid != os.geteuid()
                or stat.S_IMODE(parent.st_mode) & 0o077):
            raise RotationKitError("ROTATION_OUTPUT_UNSAFE")
        try:
            descriptor = os.open(
                path.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL
                | getattr(os, "O_NOFOLLOW", 0)
                | getattr(os, "O_CLOEXEC", 0),
                0o600, dir_fd=parent_fd,
            )
        except OSError as exc:
            raise RotationKitError(
                "ROTATION_OUTPUT_EXISTS_OR_UNSAFE"
            ) from exc
        created = True
        view = memoryview(raw)
        while view:
            written = os.write(descriptor, view)
            if written <= 0:
                raise RotationKitError("ROTATION_OUTPUT_WRITE_FAILED")
            view = view[written:]
        os.fsync(descriptor)
        info = os.fstat(descriptor)
        if (not stat.S_ISREG(info.st_mode)
                or info.st_uid != os.geteuid()
                or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_nlink != 1 or info.st_size != len(raw)):
            raise RotationKitError("ROTATION_OUTPUT_UNSAFE")
        os.fsync(parent_fd)
    except BaseException:
        if created:
            try:
                os.unlink(path.name, dir_fd=parent_fd)
            except OSError:
                pass
        raise
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        os.close(parent_fd)
    return _sha(raw)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    os.umask(0o077)
    try:
        release = _release_root()
        archive = build_archive(
            _source_files(release), implementation_commit=release.name,
        )
        digest = _write_new(args.out, archive)
        receipt = {
            "schemaVersion": "b64-064a-reviewer-key-rotation-kit-receipt.v1",
            "route": ROUTE,
            "status": "SECRET_FREE_REVIEWER_ROTATION_KIT_CREATED",
            "implementationCommit": release.name,
            "archiveSha256": digest,
            "archiveBytes": len(archive),
            "fileCount": 6,
            "containsPrivateKey": False,
            "containsPassphrase": False,
            "productionAuthorityComplete": False,
            "actionAllowed": False,
        }
    except RotationKitError as exc:
        receipt = {
            "schemaVersion": "b64-064a-reviewer-key-rotation-kit-receipt.v1",
            "route": ROUTE,
            "status": "FAILED_CLOSED",
            "reason": str(exc),
            "productionAuthorityComplete": False,
            "actionAllowed": False,
        }
        print(_canonical(receipt).decode("ascii"))
        return 1
    print(_canonical(receipt).decode("ascii"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
