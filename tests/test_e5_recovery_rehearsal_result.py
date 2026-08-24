import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from test_e5_recovery_review import authorization
from core.e5_recovery_rehearsal_result import (
    REQUIRED_STEPS, build_consumption_evidence, build_rehearsal_observation,
    build_rehearsal_result, validate_rehearsal_result,
)

NOW = 1_800_000_000_000
DAY = 86_400_000


def digest(label):
    return hashlib.sha256(label.encode()).hexdigest()


def fixture(**outcomes):
    boundary, policy, attempt, proposal, review, auth = authorization()
    consumption = build_consumption_evidence(
        authorization=auth, invocation_identity_sha256=digest("runner"),
        invoked_at_epoch_ms=NOW + DAY + 5_000)
    observations = [build_rehearsal_observation(
        authorization=auth, consumption=consumption, step_id=step,
        outcome=outcomes.get(step, "PASS"), evidence_sha256=digest(step),
        observer_identity_sha256=digest("observer"),
        observed_at_epoch_ms=NOW + DAY + 6_000 + index)
        for index, step in enumerate(REQUIRED_STEPS)]
    args = dict(
        authorization=auth, review=review, proposal=proposal, attempt=attempt,
        policy=policy, boundary=boundary, consumption=consumption,
        observations=observations,
        consumed_authorization_ids=[auth["authorizationId"]],
        attestor_identity_sha256=digest("attestor"),
        attested_at_epoch_ms=NOW + DAY + 7_000)
    return args, build_rehearsal_result(**args)


def test_complete_synthetic_rehearsal_reports_pass_but_no_security_or_readiness():
    args, result = fixture()
    assert result["status"] == "PASS" and result["isolatedRehearsalPassed"] is True
    assert result["blockers"] == []
    for field in (
        "onDeviceSecurityVerified", "productionReadinessSatisfied",
        "recoveryExecuted", "newAuthorityInstalled", "priorDeviceRevoked",
        "signingAllowed", "actionAllowed",
    ):
        assert result[field] is False
    assert validate_rehearsal_result(result, **{
        key: args[key] for key in (
            "authorization", "review", "proposal", "attempt", "policy",
            "boundary", "consumption", "observations",
            "consumed_authorization_ids")}) == result


@pytest.mark.parametrize("failed", REQUIRED_STEPS)
def test_each_failed_step_is_explicit_result_failure(failed):
    _, result = fixture(**{failed: "FAIL"})
    assert result["status"] == "FAIL"
    assert result["blockers"] == [failed]
    assert result["isolatedRehearsalPassed"] is False


def test_missing_duplicate_or_binding_drift_fails_closed():
    args, _ = fixture()
    with pytest.raises(ValueError, match="incomplete or duplicated"):
        build_rehearsal_result(**{**args, "observations": args["observations"][:-1]})
    duplicate = args["observations"][:-1] + [args["observations"][0]]
    with pytest.raises(ValueError, match="incomplete or duplicated"):
        build_rehearsal_result(**{**args, "observations": duplicate})
    changed = copy.deepcopy(args["observations"])
    changed[0]["mobileBuildSha256"] = digest("other-build")
    with pytest.raises(ValueError):
        build_rehearsal_result(**{**args, "observations": changed})


def test_consumption_is_exactly_once_and_inside_authorization_window():
    args, _ = fixture()
    changed = copy.deepcopy(args["consumption"]); changed["consumptionCount"] = 2
    with pytest.raises(ValueError):
        build_rehearsal_result(**{**args, "consumption": changed})
    with pytest.raises(ValueError, match="exactly once"):
        build_rehearsal_result(**{**args, "consumed_authorization_ids": []})
    with pytest.raises(ValueError, match="exactly once"):
        build_rehearsal_result(**{
            **args, "consumed_authorization_ids": [
                args["authorization"]["authorizationId"],
                args["authorization"]["authorizationId"]]})
    with pytest.raises(ValueError, match="outside authorization"):
        build_consumption_evidence(
            authorization=args["authorization"],
            invocation_identity_sha256=digest("runner"),
            invoked_at_epoch_ms=args["authorization"]["expiresAtEpochMs"] + 1)


def test_observation_and_attestation_time_or_independence_fails_closed():
    args, _ = fixture()
    changed = copy.deepcopy(args["observations"])
    changed[0] = build_rehearsal_observation(
        authorization=args["authorization"], consumption=args["consumption"],
        step_id=REQUIRED_STEPS[0], outcome="PASS", evidence_sha256=digest("time"),
        observer_identity_sha256=digest("observer"),
        observed_at_epoch_ms=args["consumption"]["invokedAtEpochMs"] - 1)
    with pytest.raises(ValueError, match="time"):
        build_rehearsal_result(**{**args, "observations": changed})
    with pytest.raises(ValueError, match="not independent"):
        build_rehearsal_result(**{
            **args, "attestor_identity_sha256": digest("observer")})


def test_result_capability_tamper_fails_canonical_validation():
    args, result = fixture()
    validation = {key: args[key] for key in (
        "authorization", "review", "proposal", "attempt", "policy",
        "boundary", "consumption", "observations", "consumed_authorization_ids")}
    for field, replacement in (
        ("status", "PRODUCTION_READY"), ("onDeviceSecurityVerified", True),
        ("productionReadinessSatisfied", True), ("recoveryExecuted", True),
        ("newAuthorityInstalled", True), ("priorDeviceRevoked", True),
        ("signingAllowed", True), ("executionEffect", "RECOVERY"),
        ("actionAllowed", True),
    ):
        changed = copy.deepcopy(result); changed[field] = replacement
        with pytest.raises(ValueError):
            validate_rehearsal_result(changed, **validation)


def test_contract_has_no_runner_storage_network_sdk_or_secret_surface():
    source = (ROOT / "relay/core/e5_recovery_rehearsal_result.py").read_text().lower()
    for forbidden in (
        "open(", "read_text", "read_bytes", "sqlite", "psycopg", "requests",
        "httpx", "aiohttp", "socket", "os.environ", "subprocess", "docker",
        "systemctl", "mnemonic", "private_key", "seed_phrase", "keychain",
        "keystore", "android", "ios", "sign_transaction",
    ):
        assert forbidden not in source
