import argparse
import copy
import importlib.util
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


SCRIPT = Path(__file__).parents[1] / "scripts/b64_064a_activation_ceremony.py"
SPEC = importlib.util.spec_from_file_location(
    "b64_064a_activation_ceremony_test", SCRIPT,
)
assert SPEC is not None and SPEC.loader is not None
CEREMONY = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(CEREMONY)
ACTIVATION = CEREMONY.activation


def _write(path: Path, raw: bytes, mode: int = 0o600) -> None:
    path.write_bytes(raw)
    path.chmod(mode)


def _profile(private: Ed25519PrivateKey, *, role: str, identity: str,
             domain: str) -> dict:
    public = private.public_key().public_bytes_raw()
    return {
        "schemaVersion": CEREMONY.PUBLIC_KEY_SCHEMA,
        "route": ACTIVATION.ROUTE,
        "keyId": ACTIVATION.supervisor._key_id(public),
        "identityId": identity,
        "trustDomain": domain,
        "role": role,
        "algorithm": "Ed25519",
        "publicKeyEncoding": "base64url-unpadded-raw32",
        "publicKeyB64": CEREMONY._b64(public),
    }


@pytest.fixture
def ceremony_state(tmp_path, monkeypatch):
    coordination = tmp_path / "coordination"
    coordination.mkdir(mode=0o700)
    signer = tmp_path / "signer"
    signer.mkdir(mode=0o700)
    clock = {"now": 1_800_000_000}
    production = {
        "containerName": ACTIVATION.PRODUCTION_CONTAINER,
        "containerId": "a" * 64,
        "imageId": ACTIVATION.PRODUCTION_IMAGE_ID,
        "containerPid": 4242,
        "startedAt": "2026-08-25T00:00:00Z",
        "restartCount": 0,
        "systemIdentifier": ACTIVATION.PRODUCTION_SYSTEM_IDENTIFIER,
    }
    keys = {
        "ACCOUNTABLE_OWNER": Ed25519PrivateKey.generate(),
        "INDEPENDENT_REVIEWER": Ed25519PrivateKey.generate(),
    }
    profiles = {
        "ACCOUNTABLE_OWNER": _profile(
            keys["ACCOUNTABLE_OWNER"], role="ACCOUNTABLE_OWNER",
            identity="owner_test", domain="owner_device_test",
        ),
        "INDEPENDENT_REVIEWER": _profile(
            keys["INDEPENDENT_REVIEWER"], role="INDEPENDENT_REVIEWER",
            identity="reviewer_test", domain="reviewer_device_test",
        ),
    }
    trust_keys = []
    for role, profile in profiles.items():
        public = keys[role].public_key().public_bytes_raw()
        trust_keys.append({
            "keyId": ACTIVATION.activation_key_id(public),
            "sourceEvidenceKeyId": profile["keyId"],
            "identityId": profile["identityId"],
            "trustDomain": profile["trustDomain"],
            "role": role,
            "status": "ACTIVE",
            "publicKeyB64": profile["publicKeyB64"],
        })
    trust = {
        "registryVersion": 1,
        "revokedKeys": [],
        "keys": sorted(trust_keys, key=lambda item: item["keyId"]),
        "source": {"evidenceKeyringSha256": "e" * 64},
        "registrySha256": "b" * 64,
    }
    artifacts = {
        key: ACTIVATION._artifact_bytes_and_sha256(path)[1]
        for key, path in ACTIVATION.ARTIFACT_PATHS.items()
    }

    monkeypatch.setattr(CEREMONY, "COORDINATION_ROOT", coordination)
    monkeypatch.setattr(CEREMONY, "IMPLEMENTATION_COMMIT", "c" * 40)
    monkeypatch.setattr(
        CEREMONY, "_verify_release_and_pins", lambda: dict(artifacts),
    )
    monkeypatch.setattr(CEREMONY, "_trusted_now", lambda: clock["now"])
    monkeypatch.setattr(CEREMONY, "_production_tuple", lambda: dict(production))
    monkeypatch.setattr(
        ACTIVATION, "_load_activation_trust_registry", lambda: copy.deepcopy(trust),
    )

    def immutable_verifier(*, keyring_sha256, decision_path, now,
                           plan, decision):
        verified = ACTIVATION.verify_activation_decision(
            keyring_raw=(coordination / "keyring.json").read_bytes(),
            decision_raw=decision_path.read_bytes(),
            activation_plan_raw=(
                coordination / "activation-plan.json"
            ).read_bytes(),
            expected_keyring_sha256=keyring_sha256,
            expected_environment="PRODUCTION",
            now_epoch=now,
        )
        assert verified.run_nonce == plan["runNonce"]
        assert verified.decision_sha256 == decision["decisionSha256"]
        return {
            "receiptStatus": "OK",
            "route": ACTIVATION.ROUTE,
            "status": "ACTIVATION_PACKAGE_VERIFIED_EXECUTOR_ABSENT",
            "environment": "PRODUCTION",
            "runNonce": plan["runNonce"],
            "planSha256": CEREMONY._sha(CEREMONY._canonical(plan)),
            "decisionSha256": decision["decisionSha256"],
            "productionExecutionAdapterPresent": False,
            "authorizationConsumed": False,
            "automaticRetryAllowed": False,
            "actionAllowed": False,
        }

    monkeypatch.setattr(
        CEREMONY, "_verify_with_immutable_entrypoint", immutable_verifier,
    )

    passphrase = b"correct horse battery staple"
    for role, private in keys.items():
        slug = "owner" if role == "ACCOUNTABLE_OWNER" else "reviewer"
        _write(
            signer / f"{slug}-public.json",
            CEREMONY._canonical(profiles[role]) + b"\n",
        )
        _write(
            signer / f"{slug}-private.pem",
            private.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.BestAvailableEncryption(
                    passphrase
                ),
            ),
        )

    state = {
        "coordination": coordination,
        "signer": signer,
        "clock": clock,
        "production": production,
        "trust": trust,
        "profiles": profiles,
        "passphrase": passphrase,
    }

    def prepare_unsigned():
        CEREMONY.command_build_keyring(argparse.Namespace())
        CEREMONY.command_create_plan(argparse.Namespace())
        return CEREMONY.command_create_decision(argparse.Namespace())

    def sign(role: str):
        slug = "owner" if role == "ACCOUNTABLE_OWNER" else "reviewer"
        for name in (
            "keyring.json", "activation-plan.json", "decision-unsigned.json",
        ):
            destination = signer / name
            if not destination.exists():
                shutil.copyfile(coordination / name, destination)
                destination.chmod(0o600)
        read_fd, write_fd = os.pipe()
        try:
            os.write(write_fd, passphrase + b"\n")
        finally:
            os.close(write_fd)
        try:
            decision = json.loads(
                (signer / "decision-unsigned.json").read_bytes()
            )
            result = CEREMONY.command_sign(argparse.Namespace(
                role=role,
                public_profile=str(signer / f"{slug}-public.json"),
                keyring=str(signer / "keyring.json"),
                activation_plan=str(signer / "activation-plan.json"),
                decision=str(signer / "decision-unsigned.json"),
                confirm_decision_sha256=decision["decisionSha256"],
                private_key=str(signer / f"{slug}-private.pem"),
                passphrase_fd=read_fd,
                out=str(signer / f"{slug}-signature.json"),
            ))
        finally:
            os.close(read_fd)
        shutil.copyfile(
            signer / f"{slug}-signature.json",
            coordination / f"{slug}-signature.json",
        )
        (coordination / f"{slug}-signature.json").chmod(0o600)
        return result

    state["prepare_unsigned"] = prepare_unsigned
    state["sign"] = sign
    return state


def test_full_v3_ceremony_verifies_but_creates_no_runtime_request(
        ceremony_state, tmp_path):
    decision_receipt = ceremony_state["prepare_unsigned"]()
    owner = ceremony_state["sign"]("ACCOUNTABLE_OWNER")
    reviewer = ceremony_state["sign"]("INDEPENDENT_REVIEWER")
    result = CEREMONY.command_assemble_decision(argparse.Namespace())
    verified = CEREMONY.command_verify_decision(argparse.Namespace())

    assert decision_receipt["signatureDomain"] == \
        "OBSIDIAN_B64_064A_PRODUCTION_ACTIVATION_V3"
    assert owner["productionAuthoritySignature"] is True
    assert reviewer["productionAuthoritySignature"] is True
    assert result["status"] == "SIGNED_V3_DECISION_VERIFIED_NOT_DEPLOYED"
    assert result["productionAuthorityComplete"] is True
    assert result["runtimeRequestsCreated"] is False
    assert result["launcherStarted"] is False
    assert verified["decisionSha256"] == result["decisionSha256"]
    assert not (tmp_path / "launch.request").exists()
    assert not (tmp_path / "recovery.request").exists()


def test_secret_free_offline_kit_is_deterministic_and_content_bound(
        ceremony_state):
    first = ceremony_state["signer"] / "kit-one.tar"
    second = ceremony_state["signer"] / "kit-two.tar"
    one = CEREMONY.command_build_offline_kit(argparse.Namespace(out=str(first)))
    two = CEREMONY.command_build_offline_kit(argparse.Namespace(out=str(second)))
    assert one["archiveSha256"] == two["archiveSha256"]
    assert first.read_bytes() == second.read_bytes()
    with tarfile.open(first) as archive:
        names = set(archive.getnames())
        assert names == {
            *CEREMONY.OFFLINE_KIT_FILES,
            "KIT-MANIFEST.json", "README.txt", "SHA256SUMS",
            "owner-public.json", "reviewer-public.json",
        }
        assert all(member.isfile() and member.mode == 0o600
                   for member in archive.getmembers())
        manifest_file = archive.extractfile("KIT-MANIFEST.json")
        sums_file = archive.extractfile("SHA256SUMS")
        assert manifest_file is not None and sums_file is not None
        manifest = json.loads(manifest_file.read())
        sums = sums_file.read()
    assert manifest["schemaVersion"] == CEREMONY.OFFLINE_KIT_SCHEMA
    assert manifest["implementationCommit"] == "c" * 40
    assert manifest["containsPrivateKey"] is False
    assert manifest["containsPassphrase"] is False
    assert b"private.pem" not in sums


def test_fresh_request_archive_and_imported_signatures_are_exact(
        ceremony_state):
    ceremony_state["prepare_unsigned"]()
    request = ceremony_state["signer"] / "request.tar"
    exported = CEREMONY.command_export_signing_request(
        argparse.Namespace(out=str(request))
    )
    with tarfile.open(request) as archive:
        assert set(archive.getnames()) == {
            "REQUEST-MANIFEST.json", "SHA256SUMS",
            "activation-plan.json", "decision-unsigned.json", "keyring.json",
        }
        manifest_file = archive.extractfile("REQUEST-MANIFEST.json")
        assert manifest_file is not None
        manifest = json.loads(manifest_file.read())
    assert manifest["decisionSha256"] == exported["decisionSha256"]
    assert manifest["containsPrivateKey"] is False
    assert manifest["containsRuntimeRequest"] is False

    ceremony_state["sign"]("ACCOUNTABLE_OWNER")
    imported_path = ceremony_state["coordination"] / "owner-signature.json"
    imported_path.unlink()
    result = CEREMONY.command_import_signature(argparse.Namespace(
        role="ACCOUNTABLE_OWNER",
        signature=str(ceremony_state["signer"] / "owner-signature.json"),
    ))
    assert result["status"] == "FRESH_DETACHED_SIGNATURE_IMPORTED"
    assert result["productionAuthoritySignature"] is True
    assert result["productionAuthorityComplete"] is False


def test_offline_signature_output_does_not_require_hardlinks(
        ceremony_state, monkeypatch):
    ceremony_state["prepare_unsigned"]()

    def hardlinks_forbidden(*_args, **_kwargs):
        raise PermissionError("android app-private filesystem")

    monkeypatch.setattr(CEREMONY.os, "link", hardlinks_forbidden)

    result = ceremony_state["sign"]("INDEPENDENT_REVIEWER")

    output = ceremony_state["signer"] / "reviewer-signature.json"
    assert result["productionAuthoritySignature"] is True
    assert output.is_file()
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.stat().st_nlink == 1


def test_offline_output_failure_is_removed_and_existing_file_is_preserved(
        tmp_path, monkeypatch):
    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    failed = private / "failed.json"

    monkeypatch.setattr(
        CEREMONY.os, "fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError("fsync failed")),
    )
    with pytest.raises(CEREMONY.CeremonyError, match="OUTPUT_WRITE_FAILED"):
        CEREMONY._write_offline_path(str(failed), b"result\n")
    assert not failed.exists()

    monkeypatch.undo()
    existing = private / "existing.json"
    _write(existing, b"original\n")
    with pytest.raises(
        CEREMONY.CeremonyError,
        match="OUTPUT_ALREADY_EXISTS_OR_UNSAFE",
    ):
        CEREMONY._write_offline_path(str(existing), b"replacement\n")
    assert existing.read_bytes() == b"original\n"


def test_import_rejects_cryptographically_invalid_signature(ceremony_state):
    ceremony_state["prepare_unsigned"]()
    ceremony_state["sign"]("ACCOUNTABLE_OWNER")
    (ceremony_state["coordination"] / "owner-signature.json").unlink()
    source = ceremony_state["signer"] / "owner-signature.json"
    value = json.loads(source.read_bytes())
    first = "A" if value["signatureB64"][0] != "A" else "B"
    value["signatureB64"] = first + value["signatureB64"][1:]
    invalid = ceremony_state["signer"] / "invalid-signature.json"
    _write(invalid, CEREMONY._canonical(value) + b"\n")
    with pytest.raises(
        CEREMONY.CeremonyError,
        match="INVALID_DETACHED_ACTIVATION_SIGNATURE",
    ):
        CEREMONY.command_import_signature(argparse.Namespace(
            role="ACCOUNTABLE_OWNER", signature=str(invalid),
        ))


def test_keyring_cannot_self_declare_counterfeit_identity(ceremony_state):
    ceremony_state["prepare_unsigned"]()
    path = ceremony_state["coordination"] / "keyring.json"
    keyring = json.loads(path.read_bytes())
    keyring["keys"][0]["identityId"] = "counterfeit"
    unsigned = {key: keyring[key] for key in (
        "schemaVersion", "route", "trustEnvironment", "registryVersion",
        "issuedAtEpoch", "expiresAtEpoch", "revokedKeys", "keys",
    )}
    keyring["keyringSha256"] = CEREMONY._sha(CEREMONY._canonical(unsigned))
    with pytest.raises(
        CEREMONY.CeremonyError, match="ACTIVATION_TRUST_REGISTRY_MISMATCH",
    ):
        CEREMONY._load_keyring(
            CEREMONY._canonical(keyring),
            now_epoch=ceremony_state["clock"]["now"],
        )


def test_old_or_relabelled_detached_signature_is_rejected(ceremony_state):
    ceremony_state["prepare_unsigned"]()
    ceremony_state["sign"]("ACCOUNTABLE_OWNER")
    ceremony_state["sign"]("INDEPENDENT_REVIEWER")
    path = ceremony_state["coordination"] / "owner-signature.json"
    signature = json.loads(path.read_bytes())
    signature["schemaVersion"] = "b64-064a-evidence-signature.v2"
    _write(path, CEREMONY._canonical(signature) + b"\n")
    with pytest.raises(
        CEREMONY.CeremonyError, match="DETACHED_SIGNATURE_BINDING_MISMATCH",
    ):
        CEREMONY.command_assemble_decision(argparse.Namespace())


@pytest.mark.parametrize("elapsed,allowed", [(600, True), (601, False)])
def test_minimum_remaining_decision_window_is_exact(
        ceremony_state, elapsed, allowed):
    ceremony_state["prepare_unsigned"]()
    ceremony_state["sign"]("ACCOUNTABLE_OWNER")
    ceremony_state["sign"]("INDEPENDENT_REVIEWER")
    ceremony_state["clock"]["now"] += elapsed
    if allowed:
        result = CEREMONY.command_assemble_decision(argparse.Namespace())
        assert result["productionAuthorityComplete"] is True
    else:
        with pytest.raises(
            CEREMONY.CeremonyError,
            match="INSUFFICIENT_DECISION_WINDOW_REMAINING",
        ):
            CEREMONY.command_assemble_decision(argparse.Namespace())


def test_production_tuple_change_before_assembly_is_rejected(
        ceremony_state, monkeypatch):
    ceremony_state["prepare_unsigned"]()
    ceremony_state["sign"]("ACCOUNTABLE_OWNER")
    ceremony_state["sign"]("INDEPENDENT_REVIEWER")
    changed = dict(ceremony_state["production"])
    changed["containerId"] = "d" * 64
    monkeypatch.setattr(CEREMONY, "_production_tuple", lambda: changed)
    with pytest.raises(
        CEREMONY.CeremonyError,
        match="PRODUCTION_TARGET_CHANGED_DURING_CEREMONY",
    ):
        CEREMONY.command_assemble_decision(argparse.Namespace())


def test_production_tuple_accepts_exact_deployed_watchdog_contract(
        monkeypatch):
    report = {
        "status": "DORMANT_VERIFIED",
        "watchdogReady": True,
        "roleLoginState": "DISABLED",
        "credentialState": "ABSENT",
        "activeSessions": 0,
        "customerRowsRead": False,
        "authorityIncreased": False,
        "systemIdentifier": ACTIVATION.PRODUCTION_SYSTEM_IDENTIFIER,
        "container": {
            "containerId": "a" * 64,
            "containerPid": 4242,
            "health": "healthy",
            "imageId": ACTIVATION.PRODUCTION_IMAGE_ID,
            "restartCount": 0,
            "startedAt": "2026-08-25T00:00:00Z",
        },
    }
    monkeypatch.setattr(
        CEREMONY, "_fixed_subprocess", lambda *args, **kwargs: report,
    )

    observed = CEREMONY._production_tuple()

    assert observed["containerId"] == "a" * 64
    assert observed["systemIdentifier"] == \
        ACTIVATION.PRODUCTION_SYSTEM_IDENTIFIER


@pytest.mark.parametrize("authority", [None, True])
def test_production_tuple_rejects_missing_or_increased_authority(
        monkeypatch, authority):
    report = {
        "status": "DORMANT_VERIFIED",
        "watchdogReady": True,
        "roleLoginState": "DISABLED",
        "credentialState": "ABSENT",
        "activeSessions": 0,
        "customerRowsRead": False,
        "systemIdentifier": ACTIVATION.PRODUCTION_SYSTEM_IDENTIFIER,
        "container": {
            "containerId": "a" * 64,
            "containerPid": 4242,
            "health": "healthy",
            "imageId": ACTIVATION.PRODUCTION_IMAGE_ID,
            "restartCount": 0,
            "startedAt": "2026-08-25T00:00:00Z",
        },
    }
    if authority is not None:
        report["authorityIncreased"] = authority
    monkeypatch.setattr(
        CEREMONY, "_fixed_subprocess", lambda *args, **kwargs: report,
    )

    with pytest.raises(
        CEREMONY.CeremonyError, match="PRODUCTION_DORMANT_TUPLE_INVALID",
    ):
        CEREMONY._production_tuple()


def test_private_key_and_passphrase_never_enter_output(ceremony_state):
    ceremony_state["prepare_unsigned"]()
    result = ceremony_state["sign"]("ACCOUNTABLE_OWNER")
    raw = (
        ceremony_state["signer"] / "owner-signature.json"
    ).read_bytes()
    private_raw = (
        ceremony_state["signer"] / "owner-private.pem"
    ).read_bytes()
    assert ceremony_state["passphrase"] not in raw
    assert private_raw not in raw
    assert ceremony_state["passphrase"].decode() not in json.dumps(result)


def test_path_guards_reject_unsafe_parent_symlink_hardlink_and_overwrite(
        tmp_path):
    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    source = safe / "source.json"
    _write(source, b"{}\n")
    linked = safe / "linked.json"
    os.link(source, linked)
    with pytest.raises(CEREMONY.CeremonyError, match="UNSAFE_INPUT"):
        CEREMONY._read_path(str(source))
    source.unlink()
    linked.unlink()

    target = safe / "target.json"
    target.symlink_to("absent.json")
    with pytest.raises(
        CEREMONY.CeremonyError, match="OUTPUT_ALREADY_EXISTS_OR_UNSAFE",
    ):
        CEREMONY._atomic_write_path(str(target), b"{}\n")
    target.unlink()

    unsafe = tmp_path / "unsafe"
    unsafe.mkdir(mode=0o755)
    with pytest.raises(CEREMONY.CeremonyError, match="UNSAFE_PARENT"):
        CEREMONY._atomic_write_path(str(unsafe / "out.json"), b"{}\n")

    real = safe / "real.json"
    _write(real, b"{}\n")
    alias = safe / "alias.json"
    alias.symlink_to(real)
    with pytest.raises(CEREMONY.CeremonyError, match="UNSAFE_INPUT"):
        CEREMONY._read_path(str(alias))


def test_online_parser_has_no_caller_controlled_target_time_nonce_or_hook():
    parser = CEREMONY.parser()
    for command, argument in (
        ("create-plan", "--nonce"),
        ("create-plan", "--container"),
        ("create-unsigned-decision", "--now"),
        ("assemble-decision", "--signer-command"),
        ("verify-decision", "--release-root"),
    ):
        with pytest.raises(SystemExit):
            parser.parse_args([command, argument, "attacker-controlled"])


def test_unpinned_implementation_cannot_run(monkeypatch):
    monkeypatch.setattr(CEREMONY, "IMPLEMENTATION_COMMIT", "IMPLEMENTATION_COMMIT")
    with pytest.raises(
        CEREMONY.CeremonyError, match="IMPLEMENTATION_COMMIT_NOT_PINNED",
    ):
        CEREMONY._verify_release_and_pins()


def test_ceremony_pins_exact_immutable_implementation():
    assert CEREMONY.IMPLEMENTATION_COMMIT == \
        "e466268d9c518c7025f3b6c5b2f3d23407e5a4e9"
