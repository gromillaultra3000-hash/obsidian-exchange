import base64
import copy
import hashlib
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "deploy/postgres/b64_064a_activation_entrypoint.py"
sys.path.insert(0, str(MODULE_PATH.parent))
SPEC = importlib.util.spec_from_file_location(
    "b64_064a_activation_entrypoint", MODULE_PATH,
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _package(*, now: int = 1_800_000_000, environment: str =
             "DISPOSABLE_CONTRACT", plan_age: int = 100):
    owner = Ed25519PrivateKey.generate()
    reviewer = Ed25519PrivateKey.generate()
    private_keys = {
        "ACCOUNTABLE_OWNER": owner,
        "INDEPENDENT_REVIEWER": reviewer,
    }
    entries = []
    for role, identity, domain in (
        ("ACCOUNTABLE_OWNER", "owner_identity_2026",
         "owner_offline_device"),
        ("INDEPENDENT_REVIEWER", "reviewer_identity_2026",
         "reviewer_offline_device"),
    ):
        public = private_keys[role].public_key().public_bytes_raw()
        entries.append({
            "keyId": MODULE.supervisor._key_id(public),
            "identityId": identity,
            "trustDomain": domain,
            "role": role,
            "status": "ACTIVE",
            "publicKeyB64": _b64(public),
        })
    keyring_unsigned = {
        "schemaVersion": MODULE.supervisor.KEYRING_SCHEMA,
        "route": MODULE.ROUTE,
        "trustEnvironment": "PRODUCTION_AUTHENTICATED",
        "registryVersion": 2,
        "issuedAtEpoch": now - 300,
        "expiresAtEpoch": now + 3600,
        "revokedKeys": [],
        "keys": entries,
    }
    keyring_sha = hashlib.sha256(
        MODULE._canonical(keyring_unsigned)
    ).hexdigest()
    keyring = {**keyring_unsigned, "keyringSha256": keyring_sha}
    artifacts = {
        key: hashlib.sha256(path.read_bytes()).hexdigest()
        for key, path in MODULE.ARTIFACT_PATHS.items()
    }
    plan_args = {
        "environment": environment,
        "run_nonce": _b64(b"activation-run-01"),
        "created_at_epoch": now - plan_age,
        "container_id": "1" * 64,
        "image_id": (
            MODULE.PRODUCTION_IMAGE_ID if environment == "PRODUCTION"
            else "sha256:" + "2" * 64
        ),
        "system_identifier": (
            MODULE.PRODUCTION_SYSTEM_IDENTIFIER
            if environment == "PRODUCTION" else "1234567890123456789"
        ),
        "artifacts_sha256": artifacts,
    }
    if environment == "DISPOSABLE_CONTRACT":
        plan_args["container_name"] = "b64-hba-contract-1700000000"
    plan = MODULE.build_plan(**plan_args)
    plan_sha = hashlib.sha256(MODULE._canonical(plan)).hexdigest()
    authority = (
        MODULE.PRODUCTION_AUTHORITY if environment == "PRODUCTION"
        else MODULE.CONTRACT_AUTHORITY
    )
    unsigned = {
        "schemaVersion": MODULE.DECISION_SCHEMA,
        "route": MODULE.ROUTE,
        "decision": "AUTHORIZE_ONE_BOUNDED_READ_ONLY_REFRESH",
        "environment": environment,
        "activationPlanSha256": plan_sha,
        "keyringSha256": keyring_sha,
        "issuedAtEpoch": now - 60,
        "expiresAtEpoch": now + 600,
        "nonce": plan["runNonce"],
        "limits": copy.deepcopy(MODULE.LIMITS),
        "authority": copy.deepcopy(authority),
    }
    payload = MODULE.SIGNATURE_DOMAIN + MODULE._canonical(unsigned)
    signatures = []
    for entry in reversed(entries):
        role = entry["role"]
        signatures.append({
            "role": role,
            "keyId": entry["keyId"],
            "identityId": entry["identityId"],
            "signatureB64": _b64(private_keys[role].sign(payload)),
        })
    decision = {
        **unsigned,
        "decisionSha256": hashlib.sha256(
            MODULE._canonical(unsigned)
        ).hexdigest(),
        "signatures": signatures,
    }
    return {
        "now": now,
        "keyring": keyring,
        "keyring_sha": keyring_sha,
        "plan": plan,
        "decision": decision,
        "private_keys": private_keys,
    }


def _verify(package):
    return MODULE.verify_activation_decision(
        keyring_raw=MODULE._canonical(package["keyring"]),
        decision_raw=MODULE._canonical(package["decision"]),
        activation_plan_raw=MODULE._canonical(package["plan"]),
        expected_keyring_sha256=package["keyring_sha"],
        expected_environment=package["plan"]["environment"],
        now_epoch=package["now"],
    )


def _dormant():
    return {
        "loginState": "DISABLED",
        "credentialState": "ABSENT",
        "activeSessions": 0,
        "customerRowsRead": False,
    }


def _receipt(authorization, **overrides):
    value = {
        "schemaVersion": MODULE.EXECUTION_RECEIPT_SCHEMA,
        "route": MODULE.ROUTE,
        "environment": authorization.environment,
        "runNonce": authorization.run_nonce,
        "planSha256": authorization.plan_sha256,
        "decisionSha256": authorization.decision_sha256,
        "status": "COMPLETED_DORMANT_VERIFIED",
        "archiveBytes": 4096,
        "archiveSha256": hashlib.sha256(b"archive").hexdigest(),
        "catalogEquality": True,
        "tableEquality": True,
        "credentialIssued": True,
        "credentialRevoked": True,
        "sourceSessionClosed": True,
        "readerLoginState": "DISABLED",
        "readerCredentialState": "ABSENT",
        "readerActiveSessions": 0,
        "registeredWorkspaceAbsent": True,
        "dumpContainerAbsent": True,
        "restoreContainerAbsent": True,
        "containerTmpfsLifetimesEnded": True,
        "productionDataRetained": False,
        "automaticRetryAllowed": False,
        "actionAllowed": False,
    }
    value.update(overrides)
    return value


class FakeExecutor:
    production_contact = False

    def __init__(self, *, failure=None, overrides=None):
        self.failure = failure
        self.overrides = overrides or {}
        self.calls = 0

    def execute(self, plan, authorization, deadline):
        self.calls += 1
        assert plan["runNonce"] == authorization.run_nonce
        assert type(deadline) is float
        if self.failure is not None:
            raise MODULE.ActivationError(self.failure)
        return _receipt(authorization, **self.overrides)


def _run(package, journal_root, executor, **overrides):
    arguments = {
        "keyring_raw": MODULE._canonical(package["keyring"]),
        "decision_raw": MODULE._canonical(package["decision"]),
        "activation_plan_raw": MODULE._canonical(package["plan"]),
        "expected_keyring_sha256": package["keyring_sha"],
        "expected_environment": package["plan"]["environment"],
        "now_epoch": package["now"],
        "journal_root": journal_root,
        "executor": executor,
        "reconcile": _dormant,
        "verify_dormant": _dormant,
    }
    arguments.update(overrides)
    return MODULE.run_once(**arguments)


def test_two_signatures_authorize_only_exact_fresh_activation_plan():
    package = _package()
    verified = _verify(package)
    assert verified.environment == "DISPOSABLE_CONTRACT"
    assert verified.run_nonce == package["plan"]["runNonce"]
    assert verified.limits == MODULE.LIMITS
    assert verified.target["containerName"] == \
        "b64-hba-contract-1700000000"


@pytest.mark.parametrize("drift", [
    "plan", "authority", "authority_type_alias", "signature", "expired",
    "wrong_environment", "wrong_nonce", "keyring", "duplicate_json_key",
    "stale_plan",
])
def test_tamper_replay_alias_and_stale_plan_fail_closed(drift):
    package = _package(plan_age=100 if drift != "stale_plan" else 1000)
    if drift == "plan":
        package["plan"]["target"]["containerId"] = "3" * 64
    elif drift == "authority":
        package["decision"]["authority"]["moneyActionAuthorized"] = True
    elif drift == "authority_type_alias":
        package["decision"]["authority"]["moneyActionAuthorized"] = 0
    elif drift == "signature":
        package["decision"]["signatures"][0]["signatureB64"] = _b64(b"x" * 64)
    elif drift == "expired":
        package["now"] = package["decision"]["expiresAtEpoch"]
    elif drift == "wrong_environment":
        package["decision"]["environment"] = "PRODUCTION"
    elif drift == "wrong_nonce":
        package["decision"]["nonce"] = _b64(b"different-nonce-01")
    elif drift == "keyring":
        package["keyring"]["registryVersion"] = 3
    with pytest.raises(MODULE.ActivationError):
        if drift == "duplicate_json_key":
            raw = MODULE._canonical(package["decision"])
            MODULE.verify_activation_decision(
                keyring_raw=MODULE._canonical(package["keyring"]),
                decision_raw=raw[:-1] + b',"route":"duplicate"}',
                activation_plan_raw=MODULE._canonical(package["plan"]),
                expected_keyring_sha256=package["keyring_sha"],
                expected_environment="DISPOSABLE_CONTRACT",
                now_epoch=package["now"],
            )
        else:
            _verify(package)


def test_evidence_acceptance_signature_domain_cannot_authorize_activation():
    package = _package()
    decision = package["decision"]
    unsigned = {key: decision[key] for key in (
        "schemaVersion", "route", "decision", "environment",
        "activationPlanSha256", "keyringSha256", "issuedAtEpoch",
        "expiresAtEpoch", "nonce", "limits", "authority",
    )}
    evidence_domain = MODULE.supervisor.SIGNATURE_DOMAIN
    payload = evidence_domain + MODULE._canonical(unsigned)
    for signature in decision["signatures"]:
        signature["signatureB64"] = _b64(
            package["private_keys"][signature["role"]].sign(payload)
        )
    with pytest.raises(MODULE.ActivationError,
                       match="ACTIVATION_SIGNATURE_INVALID"):
        _verify(package)


def test_live_artifact_drift_fails_before_signature_authority(monkeypatch,
                                                               tmp_path):
    package = _package()
    drifted = tmp_path / "drifted-entrypoint.py"
    drifted.write_bytes(b"drifted\n")
    drifted.chmod(0o600)
    monkeypatch.setitem(
        MODULE.ARTIFACT_PATHS, "activationEntrypoint", drifted,
    )
    with pytest.raises(MODULE.ActivationError,
                       match="ACTIVATION_ARTIFACT_DRIFT"):
        _verify(package)


def test_success_closes_journal_and_exact_decision_cannot_replay(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    executor = FakeExecutor()
    result = _run(package, tmp_path, executor)
    assert result["status"] == "ACTIVATION_COMPLETED_DORMANT_VERIFIED"
    assert result["journalState"] == "CLOSED"
    authorization = _verify(package)
    journal = MODULE.ActivationJournal(tmp_path, authorization).inspect()
    assert journal["state"] == "CLOSED"
    assert journal["attempt"] == 1
    assert journal["retryAllowed"] is False
    with pytest.raises(MODULE.ActivationError,
                       match="ACTIVATION_REPLAY_OR_INCOMPLETE"):
        _run(package, tmp_path, executor)
    assert executor.calls == 1


def test_executor_failure_is_hold_and_never_retried(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    executor = FakeExecutor(failure="SYNTHETIC_EXECUTION_FAILURE")
    with pytest.raises(MODULE.ActivationError,
                       match="SYNTHETIC_EXECUTION_FAILURE"):
        _run(package, tmp_path, executor)
    authorization = _verify(package)
    journal = MODULE.ActivationJournal(tmp_path, authorization).inspect()
    assert journal["state"] == "HOLD"
    assert journal["reasonCode"] == "SYNTHETIC_EXECUTION_FAILURE"
    with pytest.raises(MODULE.ActivationError,
                       match="ACTIVATION_REPLAY_OR_INCOMPLETE"):
        _run(package, tmp_path, executor)
    assert executor.calls == 1


@pytest.mark.parametrize("overrides", [
    {"credentialRevoked": False},
    {"readerLoginState": "ENABLED"},
    {"readerActiveSessions": True},
    {"productionDataRetained": True},
    {"catalogEquality": False},
    {"archiveBytes": 16 * 1024 * 1024 + 1},
])
def test_incomplete_or_type_aliased_receipt_is_hold(tmp_path, overrides):
    tmp_path.chmod(0o700)
    package = _package()
    executor = FakeExecutor(overrides=overrides)
    with pytest.raises(MODULE.ActivationError,
                       match="ACTIVATION_EXECUTION_NOT_CLOSED"):
        _run(package, tmp_path, executor)
    journal = MODULE.ActivationJournal(tmp_path, _verify(package)).inspect()
    assert journal["state"] == "HOLD"


def test_abnormal_running_journal_only_reconciles_to_no_retry_hold(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    authorization = _verify(package)
    journal = MODULE.ActivationJournal(tmp_path, authorization)
    journal.claim()
    journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
    result = MODULE.reconcile_incomplete(
        authorization=authorization, journal_root=tmp_path,
        reconcile=_dormant, verify_dormant=_dormant,
    )
    assert result["status"] == "ACTIVATION_RECONCILED_HOLD"
    assert journal.inspect()["state"] == "RECONCILED_HOLD"
    assert result["automaticRetryAllowed"] is False


def test_claimed_journal_after_pre_execution_crash_reconciles_to_hold(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    authorization = _verify(package)
    journal = MODULE.ActivationJournal(tmp_path, authorization)
    journal.claim()
    result = MODULE.reconcile_incomplete(
        authorization=authorization, journal_root=tmp_path,
        reconcile=_dormant, verify_dormant=_dormant,
    )
    assert result["status"] == "ACTIVATION_RECONCILED_HOLD"
    assert journal.inspect()["state"] == "RECONCILED_HOLD"


def test_reconciler_cannot_race_live_execution_lock(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    authorization = _verify(package)
    journal = MODULE.ActivationJournal(tmp_path, authorization)
    execution_lock = journal.acquire_execution_lock()
    try:
        journal.claim()
        journal.transition(expected_state={"CLAIMED"}, state="RUNNING")
        with pytest.raises(MODULE.ActivationError,
                           match="ACTIVATION_EXECUTION_LOCKED"):
            MODULE.reconcile_incomplete(
                authorization=authorization, journal_root=tmp_path,
                reconcile=_dormant, verify_dormant=_dormant,
            )
    finally:
        MODULE.os.close(execution_lock)


def test_preflight_dormant_failure_does_not_claim_decision(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    executor = FakeExecutor()
    bad = lambda: {**_dormant(), "loginState": "ENABLED"}
    with pytest.raises(MODULE.ActivationError,
                       match="DORMANT_RECONCILIATION_FAILED"):
        _run(package, tmp_path, executor, reconcile=bad)
    assert list(tmp_path.iterdir()) == []
    assert executor.calls == 0


def test_environment_mismatch_does_not_claim_decision(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    executor = FakeExecutor()
    executor.production_contact = True
    with pytest.raises(MODULE.ActivationError,
                       match="EXECUTOR_ENVIRONMENT_MISMATCH"):
        _run(package, tmp_path, executor)
    assert list(tmp_path.iterdir()) == []


def test_production_consumption_requires_internal_trusted_clock(monkeypatch,
                                                                 tmp_path):
    tmp_path.chmod(0o700)
    package = _package(environment="PRODUCTION")
    executor = FakeExecutor()
    executor.production_contact = True
    monkeypatch.setattr(
        MODULE.supervisor, "_trusted_now_epoch",
        lambda: (package["now"] + 10, {"source": "synthetic"}),
    )
    with pytest.raises(MODULE.ActivationError,
                       match="ACTIVATION_TRUSTED_TIME_MISMATCH"):
        _run(package, tmp_path, executor)
    assert list(tmp_path.iterdir()) == []


def test_work_deadline_preserves_cleanup_reserve_and_is_hold(tmp_path):
    tmp_path.chmod(0o700)
    package = _package()
    ticks = iter((100.0, 251.0, 251.0))
    with pytest.raises(MODULE.ActivationError,
                       match="ACTIVATION_WORK_DEADLINE_EXCEEDED"):
        _run(package, tmp_path, FakeExecutor(), monotonic=lambda: next(ticks))
    journal = MODULE.ActivationJournal(tmp_path, _verify(package)).inspect()
    assert journal["state"] == "HOLD"


def test_journal_root_must_be_owned_mode_0700(tmp_path):
    tmp_path.chmod(0o755)
    package = _package()
    with pytest.raises(MODULE.ActivationError, match="JOURNAL_ROOT_UNSAFE"):
        _run(package, tmp_path, FakeExecutor())


def test_cli_verifies_packages_but_exposes_no_execution_switch():
    source = MODULE_PATH.read_text("utf-8")
    assert 'add_argument("--execute"' not in source
    assert 'add_argument("--activate"' not in source
    completed = subprocess.run(
        [sys.executable, str(MODULE_PATH), "--help"],
        capture_output=True, text=True, check=False,
    )
    assert completed.returncode == 0
    assert "--verify-package" in completed.stdout
    assert '"receiptStatus":"ERROR"' not in completed.stdout
    assert completed.stderr == ""
