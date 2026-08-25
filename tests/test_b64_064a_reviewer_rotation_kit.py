from __future__ import annotations

import hashlib
import importlib
import io
import json
import os
import sys
import tarfile
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
builder = importlib.import_module("build_b64_064a_reviewer_rotation_kit")


def _sources() -> dict[str, bytes]:
    return {name: f"source:{name}\n".encode() for name in builder.FILES}


def _archive_files(raw: bytes) -> dict[str, bytes]:
    with tarfile.open(fileobj=io.BytesIO(raw), mode="r:") as archive:
        return {
            item.name: archive.extractfile(item).read()
            for item in archive.getmembers()
        }


def test_rotation_kit_is_deterministic_secret_free_and_exact():
    commit = "a" * 40
    one = builder.build_archive(_sources(), implementation_commit=commit)
    two = builder.build_archive(_sources(), implementation_commit=commit)
    assert one == two
    files = _archive_files(one)
    assert set(files) == {
        *builder.FILES, "README.txt", "ROTATION-MANIFEST.json", "SHA256SUMS",
    }
    manifest = json.loads(files["ROTATION-MANIFEST.json"])
    assert manifest["implementationCommit"] == commit
    assert manifest["purpose"] == "ROTATE_CO_RESIDENT_REVIEWER_KEY"
    assert manifest["oldReviewerActivationKeyId"] == \
        builder.OLD_REVIEWER_ACTIVATION_KEY_ID
    assert manifest["oldReviewerEvidenceKeyId"] == \
        builder.OLD_REVIEWER_EVIDENCE_KEY_ID
    assert manifest["containsPrivateKey"] is False
    assert manifest["containsPassphrase"] is False
    assert manifest["productionAuthorityComplete"] is False
    assert b"PRIVATE KEY-----" not in one
    assert b"reviewer.key" in files["README.txt"]
    with tarfile.open(fileobj=io.BytesIO(one), mode="r:") as archive:
        assert all(item.isfile() for item in archive.getmembers())
        assert all(item.mode == 0o600 for item in archive.getmembers())
        assert all(item.uid == 0 and item.gid == 0
                   for item in archive.getmembers())
        assert all(item.mtime == 0 for item in archive.getmembers())

    expected = {
        line.split("  ", 1)[1]: line.split("  ", 1)[0]
        for line in files["SHA256SUMS"].decode().splitlines()
    }
    assert expected == {
        name: hashlib.sha256(value).hexdigest()
        for name, value in files.items() if name != "SHA256SUMS"
    }


def test_rotation_kit_rejects_wrong_source_set_and_commit():
    with pytest.raises(builder.RotationKitError, match="ROTATION_SOURCE_SET_INVALID"):
        builder.build_archive({}, implementation_commit="a" * 40)
    with pytest.raises(builder.RotationKitError, match="ROTATION_SOURCE_SET_INVALID"):
        builder.build_archive(_sources(), implementation_commit="not-a-commit")


def test_rotation_output_is_exclusive_private_and_exact(tmp_path):
    tmp_path.chmod(0o700)
    output = tmp_path / "rotation.tar"
    raw = b"secret-free archive"
    assert builder._write_new(str(output), raw) == hashlib.sha256(raw).hexdigest()
    assert output.read_bytes() == raw
    assert output.stat().st_mode & 0o777 == 0o600
    with pytest.raises(
        builder.RotationKitError, match="ROTATION_OUTPUT_EXISTS_OR_UNSAFE",
    ):
        builder._write_new(str(output), raw)


def test_workspace_builder_cannot_claim_immutable_release():
    with pytest.raises(
        builder.RotationKitError,
        match="ROTATION_BUILDER_IMMUTABLE_RELEASE_REQUIRED",
    ):
        builder._release_root()
