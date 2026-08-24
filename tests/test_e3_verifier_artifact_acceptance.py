import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_verifier_artifact_acceptance import (
    assess_artifact_measurement, build_artifact_measurement,
    validate_artifact_acceptance, validate_artifact_measurement,
)
from app.e3_verifier_deployment import assess_verifier_deployment

NOW = 1_800_000_000_000
MANIFEST = json.loads((ROOT / "kairos/deploy/kairos-independent-verifier.manifest.json").read_text())
SANDBOX = {key: True for key in (
    "privateNetwork", "afUnixOnly", "noNewPrivileges", "protectSystemStrict",
    "protectHome", "privateDevices", "emptyCapabilities", "noWritablePaths",
    "noEnvironmentFile", "automaticEnableDisabled",
)}


def measurement(**changes):
    values = dict(deployment_ref="verifier_a", measured_at_epoch_ms=NOW,
                  artifact_name=MANIFEST["artifactName"],
                  artifact_version=MANIFEST["artifactVersion"],
                  files=MANIFEST["files"],
                  service_identity={"user": "kairos-verifier",
                                    "group": "kairos-verifier", "nonLogin": True},
                  sandbox=SANDBOX, secret_scan_passed=True)
    values.update(changes)
    return build_artifact_measurement(**values)


def test_independent_measurement_accepts_four_artifact_dimensions_only():
    measured = measurement()
    result = assess_artifact_measurement(manifest=MANIFEST, measurement=measured)
    assert result["status"] == "ARTIFACT_ACCEPTED_OFFLINE"
    assert {item["observationType"] for item in result["observations"]} == {
        "SERVICE_IDENTITY", "LEAST_PRIVILEGE", "SECRET_ABSENCE",
        "ARTIFACT_PROVENANCE"}
    assert result["resultFreshnessRequired"] is True
    assert result["independentDeploymentVerified"] is False
    assert result["readinessCheckSatisfied"] is False
    assert result["runtimeEnableAllowed"] is False
    assert validate_artifact_acceptance(
        json.loads(json.dumps(result)), manifest=MANIFEST, measurement=measured) == result


def test_artifact_acceptance_cannot_complete_deployment_without_result_freshness():
    result = assess_artifact_measurement(manifest=MANIFEST, measurement=measurement())
    deployment = assess_verifier_deployment(
        result["observations"], assessed_at_epoch_ms=NOW)
    assert deployment["status"] == "NO_GO"
    assert deployment["blockers"] == ["RESULT_FRESHNESS_MISSING"]


@pytest.mark.parametrize("changes,blocker", [
    ({"artifact_version": "1.0.1"}, "ARTIFACT_PROVENANCE"),
    ({"service_identity": {"user": "root", "group": "root", "nonLogin": False}},
     "SERVICE_IDENTITY"),
    ({"sandbox": {**SANDBOX, "privateNetwork": False}}, "LEAST_PRIVILEGE"),
    ({"secret_scan_passed": False}, "SECRET_ABSENCE"),
])
def test_each_independent_measurement_dimension_fails_closed(changes, blocker):
    result = assess_artifact_measurement(
        manifest=MANIFEST, measurement=measurement(**changes))
    assert result["status"] == "NO_GO"
    assert result["blockers"] == [blocker]
    assert next(item for item in result["observations"]
                if item["observationType"] == blocker)["outcome"] == "FAIL"


def test_measurement_tamper_or_secret_surface_is_invalid():
    measured = measurement()
    for field, value in (("containsSecrets", True), ("activeProbeUsed", True),
                         ("measurementId", "ivam_" + "0" * 64)):
        changed = copy.deepcopy(measured)
        changed[field] = value
        with pytest.raises(ValueError):
            validate_artifact_measurement(changed)


def test_acceptance_tamper_cannot_claim_deployment_or_runtime_readiness():
    measured = measurement()
    result = assess_artifact_measurement(manifest=MANIFEST, measurement=measured)
    for field in ("independentDeploymentVerified", "readinessCheckSatisfied",
                  "runtimeEnableAllowed", "actionAllowed"):
        changed = copy.deepcopy(result)
        changed[field] = True
        with pytest.raises(ValueError):
            validate_artifact_acceptance(
                changed, manifest=MANIFEST, measurement=measured)


def test_contract_is_pure_and_has_no_filesystem_network_service_or_secret_surface():
    source = (ROOT / "kairos/app/e3_verifier_artifact_acceptance.py").read_text()
    for forbidden in ("open(", "read_text", "read_bytes", "subprocess", "systemctl",
                      "requests", "httpx", "aiohttp", "socket", "os.environ",
                      "apiKey", "apiSecret", "credential", "time.time"):
        assert forbidden not in source
