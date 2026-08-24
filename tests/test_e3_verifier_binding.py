import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_capability_verifier import verify_testnet_capabilities
from app.e3_paper_ledger import _hash
from app.e3_verifier_binding import (
    bind_verifier_capability_result, validate_verifier_capability_binding,
)
from app.e3_verifier_deployment import (
    OBSERVATION_TYPES, assess_verifier_deployment, build_deployment_observation,
)
from test_e3_capability_verifier import Source
from test_e3_testnet_capabilities import NOW


def evidence_set(result, *, assessed_at=NOW + 1, deployment_ref="verifier_a",
                 freshness_digest=None, outcome_by_type=None):
    outcome_by_type = outcome_by_type or {}
    digest = freshness_digest or _hash(result)
    return [build_deployment_observation(
        deployment_ref=deployment_ref, observation_type=kind,
        observed_at_epoch_ms=assessed_at,
        outcome=outcome_by_type.get(kind, "PASS"),
        evidence_sha256=digest if kind == "RESULT_FRESHNESS" else _hash({"kind": kind}),
    ) for kind in OBSERVATION_TYPES]


def artifacts(source=None, **evidence_changes):
    request, result = verify_testnet_capabilities(
        provider="bybit", account_ref="sandbox_1",
        assessed_at_epoch_ms=NOW + 1, source=source or Source())
    acceptance = assess_verifier_deployment(
        evidence_set(result, **evidence_changes), assessed_at_epoch_ms=NOW + 1)
    return request, result, acceptance


def test_exact_result_is_bound_to_accepted_independent_deployment_only_offline():
    request, result, acceptance = artifacts()
    binding = bind_verifier_capability_result(
        deployment_acceptance=acceptance, request=request, result=result)
    assert binding["status"] == "BOUND_OFFLINE"
    assert binding["independentDeploymentVerified"] is True
    assert binding["capabilityVerifiedOffline"] is True
    assert binding["restrictedTestnetReadinessSatisfied"] is False
    assert binding["runtimeEnableAllowed"] is False
    assert binding["actionAllowed"] is False
    assert validate_verifier_capability_binding(
        json.loads(json.dumps(binding)), deployment_acceptance=acceptance,
        request=request, result=result) == binding


def test_result_digest_mismatch_is_explicit_no_go():
    request, result, acceptance = artifacts(freshness_digest="0" * 64)
    binding = bind_verifier_capability_result(
        deployment_acceptance=acceptance, request=request, result=result)
    assert binding["status"] == "NO_GO"
    assert "RESULT_NOT_BOUND_TO_DEPLOYMENT" in binding["blockers"]


def test_failed_deployment_evidence_is_no_go_even_with_valid_result():
    request, result, acceptance = artifacts(
        outcome_by_type={"LEAST_PRIVILEGE": "FAIL"})
    binding = bind_verifier_capability_result(
        deployment_acceptance=acceptance, request=request, result=result)
    assert binding["status"] == "NO_GO"
    assert "INDEPENDENT_DEPLOYMENT_NOT_ACCEPTED" in binding["blockers"]


def test_blocked_capability_result_cannot_be_bound_as_verified():
    from test_e3_testnet_capabilities import complete, observation
    source = Source(complete(WITHDRAWAL_DENIAL=observation(
        "WITHDRAWAL_DENIAL", outcome="ALLOWED")))
    request, result, acceptance = artifacts(source)
    binding = bind_verifier_capability_result(
        deployment_acceptance=acceptance, request=request, result=result)
    assert binding["status"] == "NO_GO"
    assert "CAPABILITY_RESULT_NOT_VERIFIED" in binding["blockers"]


def test_acceptance_and_request_time_must_be_identical():
    request, result, _ = artifacts()
    acceptance = assess_verifier_deployment(
        evidence_set(result, assessed_at=NOW), assessed_at_epoch_ms=NOW)
    with pytest.raises(ValueError):
        bind_verifier_capability_result(
            deployment_acceptance=acceptance, request=request, result=result)


@pytest.mark.parametrize("field,value", [
    ("restrictedTestnetReadinessSatisfied", True),
    ("runtimeEnableAllowed", True), ("actionAllowed", True),
    ("bindingId", "ivcb_" + "0" * 64),
])
def test_binding_tamper_cannot_enable_runtime_or_change_identity(field, value):
    request, result, acceptance = artifacts()
    binding = bind_verifier_capability_result(
        deployment_acceptance=acceptance, request=request, result=result)
    changed = copy.deepcopy(binding)
    changed[field] = value
    with pytest.raises(ValueError):
        validate_verifier_capability_binding(
            changed, deployment_acceptance=acceptance, request=request, result=result)


def test_contract_has_no_network_service_secret_or_action_surface():
    source = (ROOT / "kairos/app/e3_verifier_binding.py").read_text()
    for forbidden in ("subprocess", "systemctl", "docker", "requests", "httpx",
                      "aiohttp", "socket", "os.environ", "apiKey", "apiSecret",
                      "credential", "time.time"):
        assert forbidden not in source
