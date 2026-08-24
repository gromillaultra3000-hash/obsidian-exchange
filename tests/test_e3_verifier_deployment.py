import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_verifier_deployment import (
    OBSERVATION_TYPES, MAX_AGE_MS, assess_verifier_deployment,
    build_deployment_observation, validate_deployment_observation,
    validate_verifier_deployment_acceptance,
)

NOW = 1_800_000_000_000


def observation(kind, **changes):
    values = dict(deployment_ref="verifier_a", observation_type=kind,
                  observed_at_epoch_ms=NOW, outcome="PASS",
                  evidence_sha256=(kind.lower().encode().hex() + "0" * 64)[:64])
    values.update(changes)
    return build_deployment_observation(**values)


def complete(**changes):
    values = {kind: observation(kind) for kind in OBSERVATION_TYPES}
    values.update(changes)
    return list(values.values())


def test_complete_independent_evidence_is_offline_accepted_but_not_ready():
    result = assess_verifier_deployment(complete(), assessed_at_epoch_ms=NOW + 1)
    assert result["status"] == "ACCEPTED_OFFLINE"
    assert result["independentDeploymentVerified"] is True
    assert result["readinessCheckSatisfied"] is False
    assert result["runtimeEnableAllowed"] is False
    assert result["actionAllowed"] is False
    assert validate_verifier_deployment_acceptance(
        json.loads(json.dumps(result))) == result


@pytest.mark.parametrize("kind", sorted(OBSERVATION_TYPES))
def test_each_required_evidence_type_is_blocking_when_missing(kind):
    result = assess_verifier_deployment(
        [item for item in complete() if item["observationType"] != kind],
        assessed_at_epoch_ms=NOW)
    assert result["status"] == "NO_GO"
    assert kind + "_MISSING" in result["blockers"]


@pytest.mark.parametrize("changes,suffix", [
    ({"outcome": "FAIL"}, "FAIL"),
    ({"outcome": "UNAVAILABLE"}, "UNAVAILABLE"),
    ({"observed_at_epoch_ms": NOW - MAX_AGE_MS - 1}, "STALE"),
    ({"observed_at_epoch_ms": NOW + 1_001}, "FUTURE"),
])
def test_failed_unavailable_stale_or_future_evidence_is_no_go(changes, suffix):
    kind = "SERVICE_IDENTITY"
    result = assess_verifier_deployment(
        complete(SERVICE_IDENTITY=observation(kind, **changes)),
        assessed_at_epoch_ms=NOW)
    assert result["status"] == "NO_GO"
    assert kind + "_" + suffix in result["blockers"]


def test_duplicate_or_mixed_deployment_evidence_is_invalid():
    with pytest.raises(ValueError):
        assess_verifier_deployment(complete() + [observation("SERVICE_IDENTITY")],
                                   assessed_at_epoch_ms=NOW)
    mixed = complete()
    mixed[0] = observation(mixed[0]["observationType"], deployment_ref="verifier_b")
    with pytest.raises(ValueError):
        assess_verifier_deployment(mixed, assessed_at_epoch_ms=NOW)


def test_secret_active_probe_and_hash_tamper_fail_closed():
    item = observation("SECRET_ABSENCE")
    for field, value in (("containsSecrets", True), ("activeProbeUsed", True),
                         ("observationId", "ivdo_" + "0" * 64)):
        changed = copy.deepcopy(item)
        changed[field] = value
        with pytest.raises(ValueError):
            validate_deployment_observation(changed)


def test_acceptance_tamper_cannot_enable_runtime():
    result = assess_verifier_deployment(complete(), assessed_at_epoch_ms=NOW)
    for field, value in (("runtimeEnableAllowed", True),
                         ("readinessCheckSatisfied", True),
                         ("actionAllowed", True)):
        changed = copy.deepcopy(result)
        changed[field] = value
        with pytest.raises(ValueError):
            validate_verifier_deployment_acceptance(changed)


def test_contract_has_no_install_service_network_secret_or_runtime_surface():
    source = (ROOT / "kairos/app/e3_verifier_deployment.py").read_text()
    for forbidden in ("subprocess", "systemctl", "docker", "requests", "httpx",
                      "aiohttp", "socket", "os.environ", "apiKey", "apiSecret",
                      "credential", "time.time"):
        assert forbidden not in source
