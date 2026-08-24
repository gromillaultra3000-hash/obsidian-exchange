#!/usr/bin/env python3
"""Bind and rehearse exact E0.4 code rollback preimages without production writes."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import stat
from pathlib import Path

from e0_4_prepare_owner_auth_release import BASES, canonical, sha, verify_bundle


TARGET_PREFIX = "/opt/obsidian-exchange/"
ALLOWED_PATHS = tuple(sorted(BASES))


def _lexists(path: Path):
    return os.path.lexists(os.fspath(path))


def _open_parent_beneath(root: Path, relative: str):
    parts = Path(relative).parts
    root_fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    current = root_fd
    try:
        for component in parts[:-1]:
            following = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW,
                                dir_fd=current)
            if current != root_fd: os.close(current)
            current = following
        return root_fd, current, parts[-1]
    except Exception:
        if current != root_fd: os.close(current)
        os.close(root_fd)
        raise


def _read_beneath(root: Path, relative: str):
    root_fd, parent_fd, leaf = _open_parent_beneath(root, relative)
    try:
        fd = os.open(leaf, os.O_RDONLY | os.O_NOFOLLOW, dir_fd=parent_fd)
        try:
            stat_result = os.fstat(fd)
            chunks = []
            while True:
                chunk = os.read(fd, 1024 * 1024)
                if not chunk: break
                chunks.append(chunk)
            return b"".join(chunks), stat_result
        finally: os.close(fd)
    finally:
        if parent_fd != root_fd: os.close(parent_fd)
        os.close(root_fd)


def _entry_exists_beneath(root: Path, relative: str):
    root_fd, parent_fd, leaf = _open_parent_beneath(root, relative)
    try:
        try:
            os.stat(leaf, dir_fd=parent_fd, follow_symlinks=False)
            return True
        except FileNotFoundError:
            return False
    finally:
        if parent_fd != root_fd: os.close(parent_fd)
        os.close(root_fd)


def _validate_release(manifest):
    items = manifest.get("candidateArtifacts")
    if not isinstance(items, list) or len(items) != len(ALLOWED_PATHS):
        raise ValueError("release candidate count mismatch")
    paths = [item.get("path") for item in items]
    if sorted(paths) != list(ALLOWED_PATHS) or len(paths) != len(set(paths)):
        raise ValueError("release candidate path allowlist mismatch")
    for item in items:
        path = item["path"]
        if Path(path).is_absolute() or ".." in Path(path).parts or item.get("targetPath") != TARGET_PREFIX + path:
            raise ValueError(f"unsafe release target binding: {path}")
        if item.get("archivePath") != "candidate/" + path:
            raise ValueError(f"unsafe release archive binding: {path}")


def _safe_members(archive: tarfile.TarFile):
    members = archive.getmembers()
    names = [member.name for member in members]
    if names != sorted(names) or len(names) != len(set(names)):
        raise ValueError("rollback members are duplicate or unsorted")
    for member in members:
        if (not member.isfile() or member.mode != 0o644 or member.mtime != 0 or
                member.uid != 0 or member.gid != 0 or member.uname or member.gname or
                member.pax_headers or member.name.startswith("/") or "\\" in member.name or
                ".." in Path(member.name).parts):
            raise ValueError(f"unsafe rollback member: {member.name}")
    return members


def _add(archive: tarfile.TarFile, name: str, raw: bytes):
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(raw), 0o644, 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    archive.addfile(info, io.BytesIO(raw))


def _read_release(path: Path, digest: str, release_id: str):
    manifest = verify_bundle(path, digest, release_id)
    _validate_release(manifest)
    with tarfile.open(path, "r") as archive:
        candidates = {item["path"]: archive.extractfile(item["archivePath"]).read()
                      for item in manifest["candidateArtifacts"]}
    return manifest, candidates


def prepare(output: Path, deployed_root: Path, release: Path, release_sha: str,
            release_id: str):
    release_manifest, _ = _read_release(release, release_sha, release_id)
    preimages, payloads = [], {}
    for candidate in release_manifest["candidateArtifacts"]:
        relative = candidate["path"]
        if _entry_exists_beneath(deployed_root, relative):
            raw, stat_result = _read_beneath(deployed_root, relative)
            if not stat.S_ISREG(stat_result.st_mode) or stat_result.st_nlink != 1:
                raise ValueError(f"unsafe deployed preimage: {relative}")
            if sha(raw) != candidate["deployedBaseSha256"]:
                raise ValueError(f"deployed preimage digest drift: {relative}")
            if stat_result.st_uid != candidate["targetUid"] or stat_result.st_gid != candidate["targetGid"]:
                raise ValueError(f"deployed preimage ownership drift: {relative}")
            archive_path = "preimages/" + relative
            payloads[archive_path] = raw
            preimages.append({"path":relative, "targetPath":candidate["targetPath"],
                              "priorState":"PRESENT", "archivePath":archive_path,
                              "sha256":sha(raw), "bytes":len(raw),
                              "mode":format(stat_result.st_mode & 0o7777, "04o"),
                              "uid":stat_result.st_uid, "gid":stat_result.st_gid})
        else:
            if candidate["deployedBaseSha256"] is not None:
                raise ValueError(f"missing deployed preimage: {relative}")
            preimages.append({"path":relative, "targetPath":candidate["targetPath"],
                              "priorState":"ABSENT", "archivePath":None,
                              "sha256":None, "bytes":0, "mode":None,
                              "uid":None, "gid":None})
    body = {
        "schemaVersion":"e0-4-owner-auth-rollback.v1",
        "route":"E0/E0.4/FEATURE_STATUS_SURFACE_MATRIX",
        "productionAuthorization":False, "deployable":False,
        "sourceReleaseId":release_id, "sourceReleaseSha256":release_sha,
        "restoreSemantics":"each file replacement is atomic; repeated rollback converges the seven-path set to six exact files and one exact prior absence",
        "preimages":preimages,
    }
    body["manifestDigest"] = sha(canonical(body))
    body["rollbackId"] = "e04rb_" + body["manifestDigest"][:32]
    payloads["rollback-manifest.json"] = canonical(body)
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as handle, tarfile.open(fileobj=handle, mode="w",
                                                     format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(payloads):
            _add(archive, name, payloads[name])
    raw = output.read_bytes()
    verify(output, sha(raw), body["rollbackId"], release_sha, release_id, release_manifest)
    return {"rollbackId":body["rollbackId"], "bundleSha256":sha(raw),
            "bundleBytes":len(raw), "preimageCount":len(preimages),
            "deployable":False, "productionAuthorization":False}


def verify(bundle: Path, expected_sha: str, expected_id: str,
           expected_release_sha: str, expected_release_id: str, release_manifest=None):
    raw = bundle.read_bytes()
    if sha(raw) != expected_sha:
        raise ValueError("rollback digest does not match external pin")
    with tarfile.open(bundle, "r") as archive:
        members = _safe_members(archive)
        manifest = json.load(archive.extractfile("rollback-manifest.json"))
        body = dict(manifest)
        body.pop("manifestDigest", None); body.pop("rollbackId", None)
        digest = sha(canonical(body))
        if manifest.get("manifestDigest") != digest or manifest.get("rollbackId") != "e04rb_" + digest[:32]:
            raise ValueError("rollback manifest identity mismatch")
        if manifest["rollbackId"] != expected_id:
            raise ValueError("rollback id does not match external pin")
        if (manifest["sourceReleaseSha256"] != expected_release_sha or
                manifest["sourceReleaseId"] != expected_release_id):
            raise ValueError("rollback source release pin mismatch")
        if (manifest.get("schemaVersion") != "e0-4-owner-auth-rollback.v1" or
                manifest.get("route") != "E0/E0.4/FEATURE_STATUS_SURFACE_MATRIX" or
                manifest.get("productionAuthorization") is not False or
                manifest.get("deployable") is not False):
            raise ValueError("rollback authority/schema mismatch")
        items = manifest.get("preimages")
        paths = [item.get("path") for item in items] if isinstance(items, list) else []
        if sorted(paths) != list(ALLOWED_PATHS) or len(paths) != len(set(paths)):
            raise ValueError("rollback preimage allowlist mismatch")
        release_by_path = ({item["path"]:item for item in release_manifest["candidateArtifacts"]}
                           if release_manifest else None)
        expected = {"rollback-manifest.json":(sha(canonical(manifest)), len(canonical(manifest)))}
        for item in manifest["preimages"]:
            path = item["path"]
            if item.get("targetPath") != TARGET_PREFIX + path:
                raise ValueError("rollback target binding mismatch")
            if release_by_path and item["targetPath"] != release_by_path[path]["targetPath"]:
                raise ValueError("rollback/release target mismatch")
            if item["priorState"] == "PRESENT":
                if (item.get("archivePath") != "preimages/" + path or
                        item.get("sha256") != BASES[path] or not isinstance(item.get("bytes"), int) or
                        item["bytes"] <= 0 or item.get("mode") != "0644" or
                        item.get("uid") != 0 or item.get("gid") != 0):
                    raise ValueError("invalid present preimage metadata")
                expected[item["archivePath"]] = (item["sha256"], item["bytes"])
            elif (item["priorState"] != "ABSENT" or item["archivePath"] is not None or
                  any(item.get(key) is not None for key in ("sha256", "mode", "uid", "gid")) or
                  item.get("bytes") != 0 or BASES[path] is not None):
                raise ValueError("invalid absence preimage")
        if [member.name for member in members] != sorted(expected):
            raise ValueError("rollback allowlist mismatch")
        for member in members:
            data = archive.extractfile(member).read()
            if (sha(data), len(data)) != expected[member.name]:
                raise ValueError(f"rollback payload mismatch: {member.name}")
    return manifest


def _atomic_write(path: Path, raw: bytes, mode: int, uid=0, gid=0):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".e04-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.chown(temporary, uid, gid)
        os.replace(temporary, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try: os.fsync(directory_fd)
        finally: os.close(directory_fd)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def rehearse(deployed_root: Path, release: Path, release_sha: str, release_id: str,
             rollback: Path, rollback_sha: str, rollback_id: str):
    release_manifest, candidates = _read_release(release, release_sha, release_id)
    rollback_manifest = verify(rollback, rollback_sha, rollback_id, release_sha, release_id,
                               release_manifest)
    ordered = [item["path"] for item in release_manifest["candidateArtifacts"]]
    preimages = {item["path"]:item for item in rollback_manifest["preimages"]}
    if set(ordered) != set(preimages):
        raise ValueError("release/rollback target mismatch")
    with tarfile.open(rollback, "r") as archive:
        old_bytes = {path:archive.extractfile(item["archivePath"]).read()
                     for path, item in preimages.items() if item["priorState"] == "PRESENT"}
    def restore(tree, limit=None):
        completed = 0
        for path in reversed(ordered):
            if limit is not None and completed >= limit: break
            item, target = preimages[path], tree / path
            if item["priorState"] == "ABSENT":
                if _lexists(target):
                    target.unlink()
                    directory_fd = os.open(target.parent, os.O_RDONLY | os.O_DIRECTORY)
                    try: os.fsync(directory_fd)
                    finally: os.close(directory_fd)
            else:
                _atomic_write(target, old_bytes[path], int(item["mode"], 8), item["uid"], item["gid"])
            completed += 1

    def assert_restored(tree):
        for path, item in preimages.items():
            target = tree / path
            if item["priorState"] == "ABSENT":
                if _lexists(target): raise AssertionError(f"absence not restored: {path}")
            else:
                stat_result = target.stat()
                if (sha(target.read_bytes()) != item["sha256"] or
                        format(stat_result.st_mode & 0o7777, "04o") != item["mode"] or
                        stat_result.st_uid != item["uid"] or stat_result.st_gid != item["gid"]):
                    raise AssertionError(f"preimage metadata not restored: {path}")

    points = []
    for replaced in range(len(ordered) + 1):
      for rollback_completed in range(len(ordered) + 1):
        with tempfile.TemporaryDirectory(prefix="e04-partial-") as td:
            tree = Path(td) / "opt/obsidian-exchange"
            for path, item in preimages.items():
                if item["priorState"] == "PRESENT":
                    raw, stat_result = _read_beneath(deployed_root, path)
                    if (not stat.S_ISREG(stat_result.st_mode) or stat_result.st_nlink != 1 or
                            sha(raw) != item["sha256"] or
                            format(stat_result.st_mode & 0o7777, "04o") != item["mode"] or
                            stat_result.st_uid != item["uid"] or stat_result.st_gid != item["gid"]):
                        raise ValueError(f"copied production preimage metadata drift: {path}")
                    _atomic_write(tree / path, raw, stat_result.st_mode & 0o7777,
                                  stat_result.st_uid, stat_result.st_gid)
                elif _entry_exists_beneath(deployed_root, path):
                    raise ValueError(f"expected production absence drift: {path}")
            for path in ordered[:replaced]:
                candidate = next(item for item in release_manifest["candidateArtifacts"] if item["path"] == path)
                _atomic_write(tree / path, candidates[path], int(candidate["mode"], 8),
                              candidate["targetUid"], candidate["targetGid"])
            restore(tree, rollback_completed)
            restore(tree)
            assert_restored(tree)
            points.append({"replacedCount":replaced,
                           "rollbackStepsBeforeInterruption":rollback_completed,
                           "recoveredAfterRerun":True})
    return {"schemaVersion":"e0-4-owner-auth-partial-recovery-rehearsal.v1",
            "sourceReleaseId":release_id, "rollbackId":rollback_id,
            "productionMutation":False, "points":points,
            "forwardReplacementPoints":len(ordered) + 1,
            "rollbackInterruptionPointsPerForwardPoint":len(ordered) + 1,
            "faultMatrixCases":len(points), "allRecovered":True}


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    action.add_argument("--rehearse", type=Path, metavar="ROLLBACK_BUNDLE")
    parser.add_argument("--deployed-root", type=Path, default=Path("/opt/obsidian-exchange"))
    parser.add_argument("--release", type=Path, required=True)
    parser.add_argument("--release-sha256", required=True)
    parser.add_argument("--release-id", required=True)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-rollback-id")
    args = parser.parse_args()
    if args.output:
        result = prepare(args.output, args.deployed_root, args.release,
                         args.release_sha256, args.release_id)
    elif args.verify:
        if not args.expected_sha256 or not args.expected_rollback_id:
            parser.error("--verify requires --expected-sha256 and --expected-rollback-id")
        release_manifest, _ = _read_release(args.release, args.release_sha256, args.release_id)
        manifest = verify(args.verify, args.expected_sha256, args.expected_rollback_id,
                          args.release_sha256, args.release_id, release_manifest)
        result = {"rollbackId":manifest["rollbackId"], "verified":True}
    else:
        if not args.expected_sha256 or not args.expected_rollback_id:
            parser.error("--rehearse requires --expected-sha256 and --expected-rollback-id")
        result = rehearse(args.deployed_root, args.release, args.release_sha256,
                          args.release_id, args.rehearse, args.expected_sha256,
                          args.expected_rollback_id)
    print(json.dumps(result, sort_keys=True))


if __name__ == "__main__":
    main()
