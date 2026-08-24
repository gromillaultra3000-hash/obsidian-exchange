import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy/postgres/b64_dump_restore_supervisor.py"
SPEC = importlib.util.spec_from_file_location(
    "b64_dump_restore_supervisor", MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _exact() -> dict:
    return {
        "evidenceSha256": MODULE.EVIDENCE_SHA256,
        "planSha256": MODULE.REHEARSAL_PLAN_SHA256,
        "artifactClosureSha256": hashlib.sha256(b"closure").hexdigest(),
    }


def _signed_acceptance(*, now: int = 1_800_000_000):
    owner = Ed25519PrivateKey.generate()
    reviewer = Ed25519PrivateKey.generate()
    entries = [
        {
            "keyId": "owner_key_2026", "identityId": "owner_identity_2026",
            "trustDomain": "owner_offline_domain", "role": "ACCOUNTABLE_OWNER",
            "status": "ACTIVE",
            "publicKeyB64": _b64(owner.public_key().public_bytes_raw()),
        },
        {
            "keyId": "review_key_2026", "identityId": "review_identity_2026",
            "trustDomain": "review_offline_domain",
            "role": "INDEPENDENT_REVIEWER", "status": "ACTIVE",
            "publicKeyB64": _b64(reviewer.public_key().public_bytes_raw()),
        },
    ]
    keyring_unsigned = {
        "schemaVersion": MODULE.KEYRING_SCHEMA, "route": MODULE.ROUTE,
        "trustEnvironment": "PRODUCTION_AUTHENTICATED", "keys": entries,
    }
    keyring_sha = hashlib.sha256(MODULE._canonical(keyring_unsigned)).hexdigest()
    keyring = {**keyring_unsigned, "keyringSha256": keyring_sha}
    exact = _exact()
    unsigned = {
        "schemaVersion": MODULE.ACCEPTANCE_SCHEMA, "route": MODULE.ROUTE,
        "decision": "ACCEPT_EXACT_DISPOSABLE_REHEARSAL_EVIDENCE_ONLY",
        "evidenceSha256": exact["evidenceSha256"],
        "planSha256": exact["planSha256"],
        "artifactClosureSha256": exact["artifactClosureSha256"],
        "keyringSha256": keyring_sha, "issuedAtEpoch": now - 60,
        "expiresAtEpoch": now + 600, "nonce": _b64(b"n" * 16),
        "authority": copy.deepcopy(MODULE.NON_AUTHORITY),
    }
    payload = MODULE.SIGNATURE_DOMAIN + MODULE._canonical(unsigned)
    acceptance = {
        **unsigned,
        "acceptanceSha256": hashlib.sha256(
            MODULE._canonical(unsigned)
        ).hexdigest(),
        "signatures": [
            {
                "role": "INDEPENDENT_REVIEWER", "keyId": "review_key_2026",
                "identityId": "review_identity_2026",
                "signatureB64": _b64(reviewer.sign(payload)),
            },
            {
                "role": "ACCOUNTABLE_OWNER", "keyId": "owner_key_2026",
                "identityId": "owner_identity_2026",
                "signatureB64": _b64(owner.sign(payload)),
            },
        ],
    }
    return keyring, acceptance, keyring_sha, exact, now


def test_supervisor_pins_exact_rehearsal_and_exposes_no_activation_entrypoint():
    evidence = ROOT / MODULE.EVIDENCE_RELATIVE_PATH
    assert hashlib.sha256(evidence.read_bytes()).hexdigest() == \
        MODULE.EVIDENCE_SHA256
    source = MODULE_PATH.read_text("utf-8")
    assert "issue_credential_lease" not in source
    assert "execute_hermetic(" not in source
    assert "dumpRestoreExecutionEntrypointPresent\": False" in source
    assert all(value is False for value in MODULE.NON_AUTHORITY.values())


def test_exact_deployed_rehearsal_release_closure_validates():
    release = Path(
        "/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a"
    ) / MODULE.REHEARSAL_RELEASE_COMMIT
    if not release.is_dir():
        pytest.skip("immutable rehearsal release is production-host evidence")
    result = MODULE.validate_exact_rehearsal(
        evidence_root=ROOT, rehearsal_root=release,
    )
    assert result["evidenceSha256"] == MODULE.EVIDENCE_SHA256
    assert result["planSha256"] == MODULE.REHEARSAL_PLAN_SHA256
    assert result["artifactCount"] == 16
    assert result["rehearsalReleaseCommit"] == MODULE.REHEARSAL_RELEASE_COMMIT


def test_two_independent_signatures_authenticate_only_exact_evidence():
    keyring, acceptance, keyring_sha, exact, now = _signed_acceptance()
    result = MODULE.verify_authenticated_acceptance(
        keyring_raw=MODULE._canonical(keyring),
        acceptance_raw=MODULE._canonical(acceptance),
        expected_keyring_sha256=keyring_sha, exact=exact, now_epoch=now,
    )
    assert result == {
        "status": "AUTHENTICATED_EXACT_EVIDENCE_ACCEPTED",
        "acceptanceSha256": acceptance["acceptanceSha256"],
        "keyringSha256": keyring_sha,
        "signerRoles": ["ACCOUNTABLE_OWNER", "INDEPENDENT_REVIEWER"],
        "readerActivationAuthorized": False,
        "productionRefreshAuthorized": False,
        "actionAllowed": False,
    }


@pytest.mark.parametrize("drift", [
    "evidence", "plan", "closure", "authority", "signature", "expired",
    "authority_type_alias", "same_identity", "untrusted_keyring",
])
def test_acceptance_tamper_and_non_independence_fail_closed(drift):
    keyring, acceptance, keyring_sha, exact, now = _signed_acceptance()
    if drift == "evidence":
        exact["evidenceSha256"] = "0" * 64
    elif drift == "plan":
        exact["planSha256"] = "1" * 64
    elif drift == "closure":
        exact["artifactClosureSha256"] = "2" * 64
    elif drift == "authority":
        acceptance["authority"]["readerLoginAuthorized"] = True
    elif drift == "authority_type_alias":
        acceptance["authority"]["readerLoginAuthorized"] = 0
    elif drift == "signature":
        acceptance["signatures"][0]["signatureB64"] = _b64(b"x" * 64)
    elif drift == "expired":
        now = acceptance["expiresAtEpoch"]
    elif drift == "same_identity":
        keyring["keys"][1]["identityId"] = keyring["keys"][0]["identityId"]
    elif drift == "untrusted_keyring":
        keyring_sha = "f" * 64
    with pytest.raises(MODULE.SupervisorError):
        MODULE.verify_authenticated_acceptance(
            keyring_raw=MODULE._canonical(keyring),
            acceptance_raw=MODULE._canonical(acceptance),
            expected_keyring_sha256=keyring_sha, exact=exact, now_epoch=now,
        )


def test_acceptance_rejects_duplicate_json_keys_before_signature_work():
    keyring, acceptance, keyring_sha, exact, now = _signed_acceptance()
    raw = MODULE._canonical(acceptance)
    tampered = raw[:-1] + b',"route":"E0/E0.3/B5.3/064A"}'
    with pytest.raises(MODULE.SupervisorError, match="DUPLICATE_JSON_KEY"):
        MODULE.verify_authenticated_acceptance(
            keyring_raw=MODULE._canonical(keyring), acceptance_raw=tampered,
            expected_keyring_sha256=keyring_sha, exact=exact, now_epoch=now,
        )


def test_cli_surface_cannot_request_execution():
    source = MODULE_PATH.read_text("utf-8")
    assert 'add_argument("--execute"' not in source
    assert 'add_argument("--activate"' not in source
    assert 'add_argument("--credential' not in source


def test_production_trusted_clock_is_ntp_synchronized_utc():
    if not Path("/run/systemd/timesync/synchronized").is_file():
        pytest.skip("systemd-timesyncd marker is production-host evidence")
    probe = subprocess.run(
        ["/usr/bin/timedatectl", "show", "--property=NTPSynchronized"],
        capture_output=True, check=False,
    )
    if probe.returncode != 0:
        pytest.skip("systemd bus is unavailable in the test sandbox")
    observed, evidence = MODULE._trusted_now_epoch()
    assert evidence["source"] == "SYSTEMD_TIMESYNCD_SYNCHRONIZED_UTC"
    assert evidence["ntpSynchronized"] is True
    assert evidence["timezone"] == "Etc/UTC"
    assert evidence["observedAtEpoch"] == observed
