#!/usr/bin/env python3
"""Offline owner/reviewer ceremony for the 064A evidence-only supervisor gate.

Private Ed25519 keys are generated and used only on the originating offline
devices.  The completed package authenticates exact rehearsal evidence and
deliberately carries no production, LOGIN, credential, refresh or money
authority.
"""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import re
import secrets
import stat
import sys
from pathlib import Path
from typing import Any, Mapping

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
)


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))
import b64_dump_restore_supervisor as supervisor  # noqa: E402


PUBLIC_KEY_SCHEMA = "b64-064a-evidence-public-key.v1"
DETACHED_SIGNATURE_SCHEMA = "b64-064a-evidence-detached-signature.v1"
MAX_FILE_BYTES = 1024 * 1024


class CeremonyError(RuntimeError):
    """Closed reason code suitable for a secret-free CLI receipt."""


def _reason(exc: BaseException) -> str:
    if (isinstance(exc, (CeremonyError, supervisor.SupervisorError))
            and re.fullmatch(r"[A-Z0-9_]+", str(exc))):
        return str(exc)
    return "UNEXPECTED_EVIDENCE_CEREMONY_FAILURE"


def _canonical(value: Any) -> bytes:
    try:
        return supervisor._canonical(value)
    except supervisor.SupervisorError as exc:
        raise CeremonyError(str(exc)) from exc


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _key_id(public_raw: bytes) -> str:
    return supervisor._key_id(public_raw)


def _walk_parent(path: Path) -> None:
    if not path.is_absolute():
        raise CeremonyError("PATH_NOT_ABSOLUTE")
    current = Path("/")
    try:
        for component in path.parent.parts[1:]:
            current /= component
            info = os.lstat(current)
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise CeremonyError("UNSAFE_PARENT")
        parent = os.stat(path.parent)
    except OSError as exc:
        raise CeremonyError("UNSAFE_PARENT") from exc
    if parent.st_uid != os.getuid() or stat.S_IMODE(parent.st_mode) & 0o077:
        raise CeremonyError("UNSAFE_PARENT")


def _read(path_text: str, *, private: bool = False) -> bytes:
    path = Path(path_text)
    _walk_parent(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) \
        | getattr(os, "O_CLOEXEC", 0)
    try:
        file_descriptor = os.open(path, flags)
    except OSError as exc:
        raise CeremonyError("UNSAFE_INPUT") from exc
    try:
        info = os.fstat(file_descriptor)
        mode = stat.S_IMODE(info.st_mode)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or info.st_size > MAX_FILE_BYTES
                or (private and mode != 0o600)
                or (not private and mode & 0o022)):
            raise CeremonyError("UNSAFE_INPUT")
        chunks: list[bytes] = []
        remaining = MAX_FILE_BYTES + 1
        while remaining:
            chunk = os.read(file_descriptor, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        result = b"".join(chunks)
        if len(result) > MAX_FILE_BYTES:
            raise CeremonyError("INPUT_TOO_LARGE")
        return result
    finally:
        os.close(file_descriptor)


def _write_new(path_text: str, value: bytes) -> str:
    path = Path(path_text)
    _walk_parent(path)
    if len(value) > MAX_FILE_BYTES:
        raise CeremonyError("OUTPUT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL \
        | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    try:
        file_descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CeremonyError("OUTPUT_ALREADY_EXISTS_OR_UNSAFE") from exc
    try:
        view = memoryview(value)
        while view:
            written = os.write(file_descriptor, view)
            if written <= 0:
                raise CeremonyError("OUTPUT_WRITE_FAILED")
            view = view[written:]
        os.fsync(file_descriptor)
    except BaseException:
        os.close(file_descriptor)
        try:
            os.unlink(path)
        except OSError:
            pass
        raise
    else:
        os.close(file_descriptor)
        directory = os.open(
            path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    return hashlib.sha256(value).hexdigest()


def _json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise CeremonyError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _json(path_text: str) -> dict[str, Any]:
    try:
        value = json.loads(
            _read(path_text).decode("utf-8"), object_pairs_hook=_json_pairs,
            parse_float=lambda _: (_ for _ in ()).throw(
                CeremonyError("FLOAT_FORBIDDEN")
            ),
        )
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise CeremonyError("INVALID_JSON") from exc
    if not isinstance(value, dict):
        raise CeremonyError("INVALID_JSON_ROOT")
    _canonical(value)
    return value


def _token(value: Any, code: str) -> str:
    if (type(value) is not str or not 1 <= len(value) <= 128
            or re.fullmatch(r"[A-Za-z0-9_-]+", value) is None):
        raise CeremonyError(code)
    return value


def _passphrase(file_descriptor: int | None, *, confirm: bool = False) -> bytes:
    if file_descriptor is None:
        value = getpass.getpass("Private-key passphrase: ").encode("utf-8")
        if confirm and value != getpass.getpass(
                "Repeat private-key passphrase: ").encode("utf-8"):
            raise CeremonyError("PASSPHRASE_MISMATCH")
    else:
        value = os.read(file_descriptor, 4097).rstrip(b"\r\n")
        if len(value) > 4096:
            raise CeremonyError("PASSPHRASE_TOO_LONG")
    if len(value) < 16:
        raise CeremonyError("PASSPHRASE_TOO_SHORT")
    return value


def _decode_public_entry(value: Mapping[str, Any]) -> tuple[dict[str, Any], bytes]:
    if set(value) != {
        "schemaVersion", "route", "keyId", "identityId", "trustDomain",
        "role", "algorithm", "publicKeyEncoding", "publicKeyB64",
    } or value.get("schemaVersion") != PUBLIC_KEY_SCHEMA \
            or value.get("route") != supervisor.ROUTE \
            or value.get("role") not in supervisor.SIGNER_ROLES \
            or value.get("algorithm") != "Ed25519" \
            or value.get("publicKeyEncoding") \
            != "base64url-unpadded-raw32":
        raise CeremonyError("INVALID_PUBLIC_KEY_ENTRY")
    entry = dict(value)
    _token(entry["identityId"], "INVALID_IDENTITY_ID")
    _token(entry["trustDomain"], "INVALID_TRUST_DOMAIN")
    try:
        public_raw = supervisor._decode_public_key(entry["publicKeyB64"])
    except supervisor.SupervisorError as exc:
        raise CeremonyError(str(exc)) from exc
    if entry["keyId"] != _key_id(public_raw):
        raise CeremonyError("PUBLIC_KEY_ID_MISMATCH")
    return entry, public_raw


def _load_keyring(
    path_text: str, *, now_epoch: int,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    value = _json(path_text)
    expected = {
        "schemaVersion", "route", "trustEnvironment", "registryVersion",
        "issuedAtEpoch", "expiresAtEpoch", "revokedKeys", "keys",
        "keyringSha256",
    }
    if (set(value) != expected
            or value.get("schemaVersion") != supervisor.KEYRING_SCHEMA
            or value.get("route") != supervisor.ROUTE
            or value.get("trustEnvironment") != "PRODUCTION_AUTHENTICATED"):
        raise CeremonyError("INVALID_EVIDENCE_KEYRING")
    unsigned = {key: value[key] for key in (
        "schemaVersion", "route", "trustEnvironment", "registryVersion",
        "issuedAtEpoch", "expiresAtEpoch", "revokedKeys", "keys",
    )}
    if value["keyringSha256"] != hashlib.sha256(_canonical(unsigned)).hexdigest():
        raise CeremonyError("EVIDENCE_KEYRING_DIGEST_MISMATCH")
    issued = value["issuedAtEpoch"]
    expires = value["expiresAtEpoch"]
    if (type(value["registryVersion"]) is not int
            or value["registryVersion"] <= 0 or type(issued) is not int
            or type(expires) is not int or issued <= 0
            or not issued < expires
            <= issued + supervisor.MAX_KEYRING_LIFETIME_SECONDS
            or not issued <= now_epoch < expires):
        raise CeremonyError("EVIDENCE_KEYRING_TIME_INVALID")
    if type(value["revokedKeys"]) is not list or len(value["revokedKeys"]) > 64:
        raise CeremonyError("INVALID_EVIDENCE_REVOCATIONS")
    revoked_ids: set[str] = set()
    for revocation in value["revokedKeys"]:
        if (not isinstance(revocation, dict) or set(revocation) != {
                "keyId", "revokedAtEpoch", "reasonCode",
        }):
            raise CeremonyError("INVALID_EVIDENCE_REVOCATION")
        key_id = _token(revocation["keyId"], "INVALID_REVOKED_KEY_ID")
        _token(revocation["reasonCode"], "INVALID_REVOCATION_REASON")
        if (key_id in revoked_ids or type(revocation["revokedAtEpoch"]) is not int
                or not 0 < revocation["revokedAtEpoch"] <= now_epoch):
            raise CeremonyError("INVALID_EVIDENCE_REVOCATION")
        revoked_ids.add(key_id)
    keys = value["keys"]
    if type(keys) is not list or len(keys) != 2:
        raise CeremonyError("INVALID_EVIDENCE_KEYRING")
    registry: dict[str, dict[str, Any]] = {}
    identities: set[str] = set()
    domains: set[str] = set()
    public_keys: set[bytes] = set()
    for key in keys:
        if not isinstance(key, dict) or set(key) != {
                "keyId", "identityId", "trustDomain", "role", "status",
                "publicKeyB64",
        } or key["status"] != "ACTIVE" \
                or key["role"] not in supervisor.SIGNER_ROLES:
            raise CeremonyError("INVALID_EVIDENCE_KEY")
        key_id = _token(key["keyId"], "INVALID_KEY_ID")
        identity = _token(key["identityId"], "INVALID_IDENTITY_ID")
        domain = _token(key["trustDomain"], "INVALID_TRUST_DOMAIN")
        try:
            public_raw = supervisor._decode_public_key(key["publicKeyB64"])
        except supervisor.SupervisorError as exc:
            raise CeremonyError(str(exc)) from exc
        if (key_id != _key_id(public_raw)
                or key_id in registry or key_id in revoked_ids
                or identity in identities or domain in domains
                or public_raw in public_keys):
            raise CeremonyError("EVIDENCE_SIGNERS_NOT_INDEPENDENT")
        registry[key_id] = {**key, "publicRaw": public_raw}
        identities.add(identity)
        domains.add(domain)
        public_keys.add(public_raw)
    if {key["role"] for key in keys} != supervisor.SIGNER_ROLES:
        raise CeremonyError("EVIDENCE_SIGNER_ROLES_MISMATCH")
    return value, registry


def _acceptance(
    *, keyring: Mapping[str, Any], exact: Mapping[str, Any], issued: int,
    expires: int, nonce: str,
) -> dict[str, Any]:
    if (type(issued) is not int or type(expires) is not int or issued <= 0
            or not issued < expires
            <= issued + supervisor.MAX_ACCEPTANCE_LIFETIME_SECONDS
            or issued < keyring["issuedAtEpoch"]
            or expires > keyring["expiresAtEpoch"]):
        raise CeremonyError("INVALID_ACCEPTANCE_WINDOW")
    try:
        supervisor._nonce(nonce)
    except supervisor.SupervisorError as exc:
        raise CeremonyError(str(exc)) from exc
    unsigned = {
        "schemaVersion": supervisor.ACCEPTANCE_SCHEMA,
        "route": supervisor.ROUTE,
        "decision": "ACCEPT_EXACT_DISPOSABLE_REHEARSAL_EVIDENCE_ONLY",
        "evidenceSha256": exact["evidenceSha256"],
        "planSha256": exact["planSha256"],
        "artifactClosureSha256": exact["artifactClosureSha256"],
        "keyringSha256": keyring["keyringSha256"],
        "issuedAtEpoch": issued,
        "expiresAtEpoch": expires,
        "nonce": nonce,
        "authority": dict(supervisor.NON_AUTHORITY),
    }
    return {
        **unsigned,
        "acceptanceSha256": hashlib.sha256(_canonical(unsigned)).hexdigest(),
        "signatures": [],
    }


def _unsigned_from_acceptance(
    value: Mapping[str, Any], *, keyring: Mapping[str, Any],
) -> dict[str, Any]:
    expected = {
        "schemaVersion", "route", "decision", "evidenceSha256",
        "planSha256", "artifactClosureSha256", "keyringSha256",
        "issuedAtEpoch", "expiresAtEpoch", "nonce", "authority",
        "acceptanceSha256", "signatures",
    }
    if set(value) != expected or value.get("signatures") != []:
        raise CeremonyError("INVALID_UNSIGNED_ACCEPTANCE")
    unsigned = {key: value[key] for key in (
        "schemaVersion", "route", "decision", "evidenceSha256",
        "planSha256", "artifactClosureSha256", "keyringSha256",
        "issuedAtEpoch", "expiresAtEpoch", "nonce", "authority",
    )}
    if (unsigned["schemaVersion"] != supervisor.ACCEPTANCE_SCHEMA
            or unsigned["route"] != supervisor.ROUTE
            or unsigned["decision"]
            != "ACCEPT_EXACT_DISPOSABLE_REHEARSAL_EVIDENCE_ONLY"
            or unsigned["keyringSha256"] != keyring["keyringSha256"]
            or not supervisor._exact(
                unsigned["authority"], supervisor.NON_AUTHORITY,
            )
            or value["acceptanceSha256"]
            != hashlib.sha256(_canonical(unsigned)).hexdigest()):
        raise CeremonyError("ACCEPTANCE_BINDING_MISMATCH")
    issued = unsigned["issuedAtEpoch"]
    expires = unsigned["expiresAtEpoch"]
    if (type(issued) is not int or type(expires) is not int or issued <= 0
            or not issued < expires
            <= issued + supervisor.MAX_ACCEPTANCE_LIFETIME_SECONDS
            or issued < keyring["issuedAtEpoch"]
            or expires > keyring["expiresAtEpoch"]):
        raise CeremonyError("INVALID_ACCEPTANCE_WINDOW")
    try:
        supervisor._nonce(unsigned["nonce"])
    except supervisor.SupervisorError as exc:
        raise CeremonyError(str(exc)) from exc
    return unsigned


def command_generate_key(args: argparse.Namespace) -> dict[str, Any]:
    role = _token(args.role, "INVALID_ROLE")
    identity = _token(args.identity_id, "INVALID_IDENTITY_ID")
    domain = _token(args.trust_domain, "INVALID_TRUST_DOMAIN")
    if role not in supervisor.SIGNER_ROLES or identity == domain:
        raise CeremonyError("INVALID_IDENTITY_PROFILE")
    password = _passphrase(args.passphrase_fd, confirm=args.passphrase_fd is None)
    private_key = Ed25519PrivateKey.generate()
    private_raw = private_key.private_bytes(
        serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
        serialization.BestAvailableEncryption(password),
    )
    public_raw = private_key.public_key().public_bytes_raw()
    entry = {
        "schemaVersion": PUBLIC_KEY_SCHEMA, "route": supervisor.ROUTE,
        "keyId": _key_id(public_raw), "identityId": identity,
        "trustDomain": domain, "role": role, "algorithm": "Ed25519",
        "publicKeyEncoding": "base64url-unpadded-raw32",
        "publicKeyB64": _b64(public_raw),
    }
    private_sha = _write_new(args.private_out, private_raw)
    try:
        public_sha = _write_new(args.public_out, _canonical(entry) + b"\n")
    except BaseException:
        try:
            os.unlink(args.private_out)
        except OSError:
            pass
        raise
    return {
        "keyId": entry["keyId"], "privateFileSha256": private_sha,
        "publicEntrySha256": public_sha, "productionAuthority": False,
    }


def command_build_keyring(args: argparse.Namespace) -> dict[str, Any]:
    public_values = [_decode_public_entry(_json(args.owner_public))[0],
                     _decode_public_entry(_json(args.reviewer_public))[0]]
    if ({value["role"] for value in public_values}
            != supervisor.SIGNER_ROLES
            or len({value["keyId"] for value in public_values}) != 2
            or len({value["identityId"] for value in public_values}) != 2
            or len({value["trustDomain"] for value in public_values}) != 2):
        raise CeremonyError("EVIDENCE_SIGNERS_NOT_INDEPENDENT")
    issued = int(args.issued_at)
    expires = int(args.expires_at)
    if (issued <= 0 or not issued < expires
            <= issued + supervisor.MAX_KEYRING_LIFETIME_SECONDS):
        raise CeremonyError("EVIDENCE_KEYRING_TIME_INVALID")
    source = _json(args.revocations)
    if set(source) != {"schemaVersion", "route", "revokedKeys"} \
            or source["schemaVersion"] \
            != "b64-064a-evidence-revocations.v1" \
            or source["route"] != supervisor.ROUTE \
            or type(source["revokedKeys"]) is not list:
        raise CeremonyError("INVALID_EVIDENCE_REVOCATIONS")
    revocations: list[dict[str, Any]] = source["revokedKeys"]
    keys = sorted(({
        "keyId": value["keyId"], "identityId": value["identityId"],
        "trustDomain": value["trustDomain"], "role": value["role"],
        "status": "ACTIVE", "publicKeyB64": value["publicKeyB64"],
    } for value in public_values), key=lambda value: value["keyId"])
    unsigned = {
        "schemaVersion": supervisor.KEYRING_SCHEMA,
        "route": supervisor.ROUTE,
        "trustEnvironment": "PRODUCTION_AUTHENTICATED",
        "registryVersion": int(args.registry_version),
        "issuedAtEpoch": issued, "expiresAtEpoch": expires,
        "revokedKeys": revocations, "keys": keys,
    }
    value = {
        **unsigned,
        "keyringSha256": hashlib.sha256(_canonical(unsigned)).hexdigest(),
    }
    # Re-read through the verifier-facing shape before publishing it.
    output = _canonical(value) + b"\n"
    output_sha = _write_new(args.out, output)
    try:
        _load_keyring(args.out, now_epoch=issued)
    except BaseException:
        try:
            os.unlink(args.out)
        except OSError:
            pass
        raise
    return {
        "keyringSha256": value["keyringSha256"],
        "outputSha256": output_sha, "revocationSnapshotChecked": True,
        "productionAuthority": False,
    }


def command_init_revocations(args: argparse.Namespace) -> dict[str, Any]:
    value = {
        "schemaVersion": "b64-064a-evidence-revocations.v1",
        "route": supervisor.ROUTE, "revokedKeys": [],
    }
    return {
        "revokedKeyCount": 0,
        "outputSha256": _write_new(args.out, _canonical(value) + b"\n"),
        "productionAuthority": False,
    }


def _exact(args: argparse.Namespace) -> dict[str, Any]:
    result = supervisor.validate_exact_rehearsal(
        evidence_root=Path(args.evidence_root),
        rehearsal_root=Path(args.rehearsal_root),
    )
    result.pop("plan")
    return result


def command_create_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    issued = int(args.issued_at)
    expires = int(args.expires_at)
    keyring, _ = _load_keyring(args.keyring, now_epoch=issued)
    value = _acceptance(
        keyring=keyring, exact=_exact(args), issued=issued, expires=expires,
        nonce=args.nonce or secrets.token_urlsafe(24),
    )
    return {
        "acceptanceSha256": value["acceptanceSha256"],
        "keyringSha256": keyring["keyringSha256"],
        "outputSha256": _write_new(args.out, _canonical(value) + b"\n"),
        "productionAuthority": False,
    }


def command_sign(args: argparse.Namespace) -> dict[str, Any]:
    acceptance = _json(args.acceptance)
    keyring, registry = _load_keyring(
        args.keyring, now_epoch=acceptance.get("issuedAtEpoch", 0),
    )
    unsigned = _unsigned_from_acceptance(
        acceptance, keyring=keyring,
    )
    role = _token(args.role, "INVALID_ROLE")
    profiles = [
        (key_id, profile) for key_id, profile in registry.items()
        if profile["role"] == role
    ]
    if role not in supervisor.SIGNER_ROLES or len(profiles) != 1:
        raise CeremonyError("INVALID_ROLE_PROFILE")
    key_id, profile = profiles[0]
    try:
        private_key = serialization.load_pem_private_key(
            _read(args.private_key, private=True),
            password=_passphrase(args.passphrase_fd),
        )
    except (TypeError, ValueError) as exc:
        raise CeremonyError("PRIVATE_KEY_DECRYPTION_FAILED") from exc
    if not isinstance(private_key, Ed25519PrivateKey) \
            or private_key.public_key().public_bytes_raw() != profile["publicRaw"]:
        raise CeremonyError("PRIVATE_KEY_PROFILE_MISMATCH")
    signature = private_key.sign(supervisor.SIGNATURE_DOMAIN + _canonical(unsigned))
    detached = {
        "schemaVersion": DETACHED_SIGNATURE_SCHEMA,
        "route": supervisor.ROUTE,
        "acceptanceSha256": acceptance["acceptanceSha256"],
        "keyringSha256": keyring["keyringSha256"], "role": role,
        "keyId": key_id, "identityId": profile["identityId"],
        "signatureB64": _b64(signature),
    }
    return {
        "acceptanceSha256": acceptance["acceptanceSha256"],
        "signatureFileSha256": _write_new(
            args.out, _canonical(detached) + b"\n",
        ),
        "role": role, "productionAuthority": False,
    }


def _signature(value: Mapping[str, Any], acceptance: Mapping[str, Any],
               keyring: Mapping[str, Any]) -> dict[str, Any]:
    if set(value) != {
        "schemaVersion", "route", "acceptanceSha256", "keyringSha256",
        "role", "keyId", "identityId", "signatureB64",
    } or value.get("schemaVersion") != DETACHED_SIGNATURE_SCHEMA \
            or value.get("route") != supervisor.ROUTE \
            or value.get("acceptanceSha256") \
            != acceptance["acceptanceSha256"] \
            or value.get("keyringSha256") != keyring["keyringSha256"]:
        raise CeremonyError("DETACHED_SIGNATURE_BINDING_MISMATCH")
    return {key: value[key] for key in (
        "role", "keyId", "identityId", "signatureB64",
    )}


def command_assemble(args: argparse.Namespace) -> dict[str, Any]:
    unsigned_acceptance = _json(args.acceptance)
    keyring, _ = _load_keyring(args.keyring, now_epoch=int(args.now))
    if args.expected_keyring_sha256 != keyring["keyringSha256"]:
        raise CeremonyError("EXPECTED_KEYRING_DIGEST_MISMATCH")
    _unsigned_from_acceptance(
        unsigned_acceptance, keyring=keyring,
    )
    signatures = [
        _signature(_json(args.reviewer_signature), unsigned_acceptance, keyring),
        _signature(_json(args.owner_signature), unsigned_acceptance, keyring),
    ]
    completed = {**unsigned_acceptance, "signatures": signatures}
    result = supervisor.verify_authenticated_acceptance(
        keyring_raw=_canonical(keyring), acceptance_raw=_canonical(completed),
        expected_keyring_sha256=keyring["keyringSha256"], exact=_exact(args),
        now_epoch=int(args.now),
    )
    return {
        **result,
        "outputSha256": _write_new(args.out, _canonical(completed) + b"\n"),
    }


def command_verify(args: argparse.Namespace) -> dict[str, Any]:
    acceptance = _json(args.acceptance)
    keyring, _ = _load_keyring(args.keyring, now_epoch=int(args.now))
    if args.expected_keyring_sha256 != keyring["keyringSha256"]:
        raise CeremonyError("EXPECTED_KEYRING_DIGEST_MISMATCH")
    result = supervisor.verify_authenticated_acceptance(
        keyring_raw=_canonical(keyring), acceptance_raw=_canonical(acceptance),
        expected_keyring_sha256=keyring["keyringSha256"], exact=_exact(args),
        now_epoch=int(args.now),
    )
    return result


def _evidence_arguments(command: argparse.ArgumentParser) -> None:
    command.add_argument("--evidence-root", default=str(ROOT))
    command.add_argument("--rehearsal-root", required=True)


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    commands = value.add_subparsers(dest="command", required=True)
    command = commands.add_parser("generate-key")
    command.add_argument("--role", required=True)
    command.add_argument("--identity-id", required=True)
    command.add_argument("--trust-domain", required=True)
    command.add_argument("--private-out", required=True)
    command.add_argument("--public-out", required=True)
    command.add_argument("--passphrase-fd", type=int)
    command = commands.add_parser("init-revocations")
    command.add_argument("--out", required=True)
    command = commands.add_parser("build-keyring")
    command.add_argument("--owner-public", required=True)
    command.add_argument("--reviewer-public", required=True)
    command.add_argument("--registry-version", required=True, type=int)
    command.add_argument("--issued-at", required=True, type=int)
    command.add_argument("--expires-at", required=True, type=int)
    command.add_argument("--revocations", required=True)
    command.add_argument("--out", required=True)
    command = commands.add_parser("create-acceptance")
    command.add_argument("--keyring", required=True)
    command.add_argument("--issued-at", required=True, type=int)
    command.add_argument("--expires-at", required=True, type=int)
    command.add_argument("--nonce")
    command.add_argument("--out", required=True)
    _evidence_arguments(command)
    command = commands.add_parser("sign")
    command.add_argument("--role", required=True)
    command.add_argument("--keyring", required=True)
    command.add_argument("--acceptance", required=True)
    command.add_argument("--private-key", required=True)
    command.add_argument("--passphrase-fd", type=int)
    command.add_argument("--out", required=True)
    command = commands.add_parser("assemble")
    command.add_argument("--keyring", required=True)
    command.add_argument("--acceptance", required=True)
    command.add_argument("--reviewer-signature", required=True)
    command.add_argument("--owner-signature", required=True)
    command.add_argument("--now", required=True, type=int)
    command.add_argument("--expected-keyring-sha256", required=True)
    command.add_argument("--out", required=True)
    _evidence_arguments(command)
    command = commands.add_parser("verify")
    command.add_argument("--keyring", required=True)
    command.add_argument("--acceptance", required=True)
    command.add_argument("--now", required=True, type=int)
    command.add_argument("--expected-keyring-sha256", required=True)
    _evidence_arguments(command)
    return value


def main() -> int:
    os.umask(0o077)
    try:
        args = parser().parse_args()
        if args.command == "generate-key":
            result = command_generate_key(args)
        elif args.command == "init-revocations":
            result = command_init_revocations(args)
        elif args.command == "build-keyring":
            result = command_build_keyring(args)
        elif args.command == "create-acceptance":
            result = command_create_acceptance(args)
        elif args.command == "sign":
            result = command_sign(args)
        elif args.command == "assemble":
            result = command_assemble(args)
        else:
            result = command_verify(args)
        print(json.dumps({
            "receiptStatus": "OK", "route": supervisor.ROUTE, **result,
        }, sort_keys=True, separators=(",", ":")))
        return 0
    except BaseException as exc:
        print(json.dumps({
            "receiptStatus": "ERROR", "route": supervisor.ROUTE,
            "errorCode": _reason(exc), "productionAuthority": False,
            "actionAllowed": False,
        }, sort_keys=True, separators=(",", ":")))
        return 3


if __name__ == "__main__":
    sys.exit(main())
