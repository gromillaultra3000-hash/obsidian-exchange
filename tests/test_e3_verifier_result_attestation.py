import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_capability_verifier import verify_testnet_capabilities
from app.e3_verifier_artifact_acceptance import assess_artifact_measurement
from app.e3_verifier_binding import bind_verifier_capability_result
from app.e3_verifier_deployment import assess_verifier_deployment
from app.e3_verifier_result_attestation import (
    attest_verifier_result, validate_verifier_result_attestation,
)
from test_e3_capability_verifier import Source
from test_e3_testnet_capabilities import NOW, complete, observation
from test_e3_verifier_artifact_acceptance import MANIFEST, measurement


def artifacts(source=None, artifact_measurement=None):
    request, result = verify_testnet_capabilities(
        provider="bybit", account_ref="sandbox_1", assessed_at_epoch_ms=NOW,
        source=source or Source())
    measured = artifact_measurement or measurement(measured_at_epoch_ms=NOW)
    accepted = assess_artifact_measurement(manifest=MANIFEST, measurement=measured)
    attestation = attest_verifier_result(
        artifact_acceptance=accepted, manifest=MANIFEST, measurement=measured,
        request=request, result=result)
    return request, result, measured, accepted, attestation


def test_exact_result_adds_only_freshness_and_completes_offline_binding():
    request, result, measured, artifact, attestation = artifacts()
    assert attestation["status"] == "ATTESTED_OFFLINE"
    assert attestation["observation"]["observationType"] == "RESULT_FRESHNESS"
    assert attestation["observation"]["evidenceSha256"] == attestation["resultEvidenceSha256"]
    deployment = assess_verifier_deployment(
        artifact["observations"] + [attestation["observation"]],
        assessed_at_epoch_ms=NOW)
    binding = bind_verifier_capability_result(
        deployment_acceptance=deployment, request=request, result=result)
    assert deployment["status"] == "ACCEPTED_OFFLINE"
    assert binding["status"] == "BOUND_OFFLINE"
    assert binding["restrictedTestnetReadinessSatisfied"] is False
    assert attestation["independentDeploymentVerified"] is False
    assert attestation["runtimeEnableAllowed"] is False
    assert validate_verifier_result_attestation(
        json.loads(json.dumps(attestation)), artifact_acceptance=artifact,
        manifest=MANIFEST, measurement=measured, request=request, result=result) == attestation


def test_valid_but_blocked_capability_is_attested_fresh_but_binding_stays_no_go():
    source = Source(complete(WITHDRAWAL_DENIAL=observation(
        "WITHDRAWAL_DENIAL", outcome="ALLOWED")))
    request, result, _, artifact, attestation = artifacts(source)
    deployment = assess_verifier_deployment(
        artifact["observations"] + [attestation["observation"]],
        assessed_at_epoch_ms=NOW)
    binding = bind_verifier_capability_result(
        deployment_acceptance=deployment, request=request, result=result)
    assert attestation["status"] == "ATTESTED_OFFLINE"
    assert attestation["capabilityVerifiedOffline"] is False
    assert binding["status"] == "NO_GO"
    assert "CAPABILITY_RESULT_NOT_VERIFIED" in binding["blockers"]


def test_rejected_artifact_cannot_produce_passing_freshness_observation():
    bad_measurement = measurement(
        measured_at_epoch_ms=NOW, secret_scan_passed=False)
    _, _, _, artifact, attestation = artifacts(
        artifact_measurement=bad_measurement)
    assert artifact["status"] == "NO_GO"
    assert attestation["status"] == "NO_GO"
    assert attestation["observation"]["outcome"] == "FAIL"


@pytest.mark.parametrize("field", [
    "independentDeploymentVerified", "readinessCheckSatisfied",
    "runtimeEnableAllowed", "actionAllowed",
])
def test_attestation_tamper_cannot_claim_runtime_or_deployment(field):
    request, result, measured, artifact, attestation = artifacts()
    changed = copy.deepcopy(attestation)
    changed[field] = True
    with pytest.raises(ValueError):
        validate_verifier_result_attestation(
            changed, artifact_acceptance=artifact, manifest=MANIFEST,
            measurement=measured, request=request, result=result)


def test_result_drift_invalidates_attestation():
    request, result, measured, artifact, attestation = artifacts()
    changed_result = copy.deepcopy(result)
    changed_result["resultId"] = "tcvr_" + "0" * 64
    with pytest.raises(ValueError):
        validate_verifier_result_attestation(
            attestation, artifact_acceptance=artifact, manifest=MANIFEST,
            measurement=measured, request=request, result=changed_result)


def test_contract_has_no_service_network_secret_clock_or_action_surface():
    source = (ROOT / "kairos/app/e3_verifier_result_attestation.py").read_text()
    for forbidden in ("open(", "read_text", "subprocess", "systemctl", "requests",
                      "httpx", "aiohttp", "socket", "os.environ", "apiKey",
                      "apiSecret", "credential", "time.time"):
        assert forbidden not in source
