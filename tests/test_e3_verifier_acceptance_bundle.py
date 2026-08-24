import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_verifier_acceptance_bundle import (
    build_verifier_acceptance_bundle, validate_verifier_acceptance_bundle,
)
from app.e3_verifier_binding import bind_verifier_capability_result
from app.e3_verifier_deployment import assess_verifier_deployment
from test_e3_verifier_result_attestation import NOW, artifacts
from test_e3_verifier_artifact_acceptance import MANIFEST


def chain():
    request, result, measured, artifact, attestation = artifacts()
    deployment = assess_verifier_deployment(
        artifact["observations"] + [attestation["observation"]],
        assessed_at_epoch_ms=NOW)
    binding = bind_verifier_capability_result(
        deployment_acceptance=deployment, request=request, result=result)
    values = dict(manifest=MANIFEST, measurement=measured,
                  artifact_acceptance=artifact, request=request, result=result,
                  attestation=attestation, deployment_acceptance=deployment,
                  capability_binding=binding)
    return values, build_verifier_acceptance_bundle(**values)


def test_complete_chain_is_reviewable_offline_but_not_production_or_ready():
    values, bundle = chain()
    assert bundle["status"] == "EVIDENCE_CHAIN_VALIDATED_OFFLINE"
    assert bundle["eligibleForOperationalReview"] is True
    assert bundle["productionDeploymentProven"] is False
    assert bundle["operationalReadinessProbeSatisfied"] is False
    assert bundle["runtimeEnableAllowed"] is False
    assert bundle["actionAllowed"] is False
    assert validate_verifier_acceptance_bundle(
        json.loads(json.dumps(bundle)), **values) == bundle


def test_deployment_must_contain_exact_artifact_and_result_observations():
    values, _ = chain()
    values["deployment_acceptance"] = assess_verifier_deployment(
        values["artifact_acceptance"]["observations"], assessed_at_epoch_ms=NOW)
    with pytest.raises(ValueError):
        build_verifier_acceptance_bundle(**values)


@pytest.mark.parametrize("field", [
    "productionDeploymentProven", "operationalReadinessProbeSatisfied",
    "runtimeEnableAllowed", "actionAllowed",
])
def test_bundle_tamper_cannot_claim_production_readiness_or_action(field):
    values, bundle = chain()
    changed = copy.deepcopy(bundle)
    changed[field] = True
    with pytest.raises(ValueError):
        validate_verifier_acceptance_bundle(changed, **values)


def test_any_inner_evidence_drift_invalidates_whole_chain():
    values, bundle = chain()
    changed = copy.deepcopy(values["measurement"])
    changed["measurementId"] = "ivam_" + "0" * 64
    values["measurement"] = changed
    with pytest.raises(ValueError):
        validate_verifier_acceptance_bundle(bundle, **values)


def test_bundle_contract_is_pure_and_has_no_runtime_surface():
    source = (ROOT / "kairos/app/e3_verifier_acceptance_bundle.py").read_text()
    for forbidden in ("open(", "read_text", "subprocess", "systemctl", "requests",
                      "httpx", "aiohttp", "socket", "os.environ", "apiKey",
                      "apiSecret", "credential", "time.time"):
        assert forbidden not in source
