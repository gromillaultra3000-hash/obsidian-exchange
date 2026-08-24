import base64
import importlib.util
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts/b64_064a_evidence_acceptance.py"
SPEC = importlib.util.spec_from_file_location(
    "b64_064a_evidence_acceptance", MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _write(path: Path, value: bytes) -> None:
    path.write_bytes(value)
    path.chmod(0o600)


def _profile(directory: Path, role: str, name: str, password: bytes):
    private = Ed25519PrivateKey.generate()
    public_raw = private.public_key().public_bytes_raw()
    private_path = directory / f"{name}.key"
    public_path = directory / f"{name}.json"
    _write(private_path, private.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    ))
    entry = {
        "schemaVersion": MODULE.PUBLIC_KEY_SCHEMA,
        "route": MODULE.supervisor.ROUTE,
        "keyId": MODULE._key_id(public_raw),
        "identityId": f"{name}_identity",
        "trustDomain": f"{name}_offline_device",
        "role": role,
        "algorithm": "Ed25519",
        "publicKeyEncoding": "base64url-unpadded-raw32",
        "publicKeyB64": _b64(public_raw),
    }
    _write(public_path, MODULE._canonical(entry) + b"\n")
    return private_path, public_path


def _password_fd(password: bytes) -> int:
    read_descriptor, write_descriptor = os.pipe()
    os.write(write_descriptor, password + b"\n")
    os.close(write_descriptor)
    return read_descriptor


def test_independent_offline_signatures_assemble_exact_non_authority(tmp_path,
                                                                    monkeypatch):
    tmp_path.chmod(0o700)
    password = b"correct horse battery staple"
    owner_private, owner_public = _profile(
        tmp_path, "ACCOUNTABLE_OWNER", "owner", password,
    )
    reviewer_private, reviewer_public = _profile(
        tmp_path, "INDEPENDENT_REVIEWER", "reviewer", password,
    )
    now = 1_800_000_000
    keyring_path = tmp_path / "keyring.json"
    revocations_path = tmp_path / "revocations.json"
    _write(revocations_path, MODULE._canonical({
        "schemaVersion": "b64-064a-evidence-revocations.v1",
        "route": MODULE.supervisor.ROUTE, "revokedKeys": [],
    }) + b"\n")
    MODULE.command_build_keyring(SimpleNamespace(
        owner_public=str(owner_public), reviewer_public=str(reviewer_public),
        registry_version=1, issued_at=now - 60, expires_at=now + 3600,
        revocations=str(revocations_path), out=str(keyring_path),
    ))
    keyring, _ = MODULE._load_keyring(str(keyring_path), now_epoch=now)
    exact = {
        "evidenceSha256": MODULE.supervisor.EVIDENCE_SHA256,
        "planSha256": MODULE.supervisor.REHEARSAL_PLAN_SHA256,
        "artifactClosureSha256": "a" * 64,
    }
    unsigned = MODULE._acceptance(
        keyring=keyring, exact=exact, issued=now - 10,
        expires=now + 600, nonce=_b64(b"n" * 16),
    )
    unsigned_path = tmp_path / "unsigned.json"
    _write(unsigned_path, MODULE._canonical(unsigned) + b"\n")

    signature_paths = {}
    for role, private_path, label in (
        ("INDEPENDENT_REVIEWER", reviewer_private, "reviewer"),
        ("ACCOUNTABLE_OWNER", owner_private, "owner"),
    ):
        signature_path = tmp_path / f"{label}-signature.json"
        descriptor = _password_fd(password)
        try:
            MODULE.command_sign(SimpleNamespace(
                acceptance=str(unsigned_path), keyring=str(keyring_path),
                role=role, private_key=str(private_path),
                passphrase_fd=descriptor, out=str(signature_path),
            ))
        finally:
            os.close(descriptor)
        signature_paths[label] = signature_path

    monkeypatch.setattr(MODULE, "_exact", lambda _: exact)
    completed_path = tmp_path / "completed.json"
    result = MODULE.command_assemble(SimpleNamespace(
        acceptance=str(unsigned_path), keyring=str(keyring_path), now=now,
        expected_keyring_sha256=keyring["keyringSha256"],
        reviewer_signature=str(signature_paths["reviewer"]),
        owner_signature=str(signature_paths["owner"]),
        out=str(completed_path),
    ))
    assert result["status"] == "AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED"
    assert result["revocationSnapshotChecked"] is True
    assert result["actionAllowed"] is False
    completed = json.loads(completed_path.read_text("utf-8"))
    assert len(completed["signatures"]) == 2
    assert all(value is False for value in completed["authority"].values())


def test_keyring_rejects_revoked_active_signer(tmp_path):
    tmp_path.chmod(0o700)
    password = b"correct horse battery staple"
    _, owner_public = _profile(
        tmp_path, "ACCOUNTABLE_OWNER", "owner", password,
    )
    _, reviewer_public = _profile(
        tmp_path, "INDEPENDENT_REVIEWER", "reviewer", password,
    )
    owner = json.loads(owner_public.read_text("utf-8"))
    revocations_path = tmp_path / "revocations.json"
    _write(revocations_path, MODULE._canonical({
        "schemaVersion": "b64-064a-evidence-revocations.v1",
        "route": MODULE.supervisor.ROUTE,
        "revokedKeys": [{
            "keyId": owner["keyId"], "revokedAtEpoch": 1_799_999_900,
            "reasonCode": "COMPROMISED",
        }],
    }) + b"\n")
    with pytest.raises(MODULE.CeremonyError,
                       match="EVIDENCE_SIGNERS_NOT_INDEPENDENT"):
        MODULE.command_build_keyring(SimpleNamespace(
            owner_public=str(owner_public),
            reviewer_public=str(reviewer_public), registry_version=1,
            issued_at=1_799_999_940, expires_at=1_800_003_600,
            revocations=str(revocations_path),
            out=str(tmp_path / "keyring.json"),
        ))


def test_ceremony_has_no_activation_or_credential_cli():
    source = MODULE_PATH.read_text("utf-8")
    assert 'add_parser("activate")' not in source
    assert 'add_parser("execute")' not in source
    assert 'add_parser("issue-credential")' not in source
    assert all(value is False for value in MODULE.supervisor.NON_AUTHORITY.values())
