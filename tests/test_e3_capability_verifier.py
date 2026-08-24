import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_capability_verifier import (
    build_capability_verifier_request, validate_capability_verifier_request,
    validate_capability_verifier_result, verify_testnet_capabilities,
)
from test_e3_testnet_capabilities import NOW, complete, observation


class Source:
    def __init__(self, observations=None, error=None, **changes):
        self.observations, self.error, self.changes = observations, error, changes
        self.calls = []

    def fetch(self, request):
        self.calls.append(request)
        if self.error:
            raise self.error
        response = {"requestId": request["requestId"], "provider": request["provider"],
                    "accountRef": request["accountRef"],
                    "observations": self.observations or complete(),
                    "containsSecrets": False}
        response.update(self.changes)
        return response


def verify(source, **changes):
    values = dict(provider="bybit", account_ref="sandbox_1",
                  assessed_at_epoch_ms=NOW + 1, source=source)
    values.update(changes)
    return verify_testnet_capabilities(**values)


def test_hermetic_source_yields_offline_verified_but_never_runtime_ready():
    source = Source()
    request, result = verify(source)
    assert source.calls == [request]
    assert request["operation"] == "FETCH_EXISTING_EVIDENCE"
    assert request["activeProbeAllowed"] is False
    assert result["status"] == "VERIFIED_OFFLINE"
    assert result["capabilityEvidence"]["offlineEligible"] is True
    assert result["independentDeploymentVerified"] is False
    assert result["readinessCheckSatisfied"] is False
    assert result["actionAllowed"] is False
    assert validate_capability_verifier_request(json.loads(json.dumps(request))) == request
    assert validate_capability_verifier_result(
        json.loads(json.dumps(result)), request=request) == result


def test_valid_but_permissive_capability_evidence_is_explicit_no_go():
    permissive = complete(WITHDRAWAL_DENIAL=observation("WITHDRAWAL_DENIAL", outcome="ALLOWED"))
    _, result = verify(Source(permissive))
    assert result["status"] == "NO_GO"
    assert result["reason"] == "CAPABILITY_BLOCKED"
    assert "WITHDRAWAL_DENIED" in result["capabilityEvidence"]["blockers"]


@pytest.mark.parametrize("source,reason", [
    (Source(error=TimeoutError("late")), "TIMEOUT"),
    (Source(error=ConnectionError("down")), "SOURCE_ERROR"),
    (Source(extra="field"), "INVALID_RESPONSE"),
    (Source(containsSecrets=True), "INVALID_RESPONSE"),
    (Source(requestId="wrong"), "INVALID_RESPONSE"),
])
def test_timeout_source_error_or_malformed_response_is_no_go_without_error_text(source, reason):
    _, result = verify(source)
    assert result["status"] == "NO_GO"
    assert result["reason"] == reason
    assert result["capabilityEvidence"] is None
    assert "late" not in json.dumps(result) and "down" not in json.dumps(result)


def test_exact_replay_does_not_call_source_and_drift_fails_before_source():
    request, result = verify(Source())
    replay_source = Source(error=AssertionError("must not call"))
    replay_request, replay_result = verify(
        replay_source, previous_result=json.loads(json.dumps(result)))
    assert replay_source.calls == []
    assert (replay_request, replay_result) == (request, result)
    changed = copy.deepcopy(result)
    changed["readinessCheckSatisfied"] = True
    with pytest.raises(ValueError):
        verify(replay_source, previous_result=changed)
    assert replay_source.calls == []


@pytest.mark.parametrize("field,value", [
    ("environment", "MAINNET"), ("activeProbeAllowed", True),
    ("containsSecrets", True), ("requestId", "tcvr_" + "0" * 64),
])
def test_request_tamper_or_active_probe_surface_fails_closed(field, value):
    request = build_capability_verifier_request(
        provider="bybit", account_ref="sandbox_1", assessed_at_epoch_ms=NOW)
    request[field] = value
    with pytest.raises(ValueError):
        validate_capability_verifier_request(request)


def test_adapter_has_no_network_sdk_secret_clock_or_action_surface():
    source = (ROOT / "kairos/app/e3_capability_verifier.py").read_text()
    for forbidden in ("apiKey", "apiSecret", "credential", "requests", "httpx",
                      "aiohttp", "socket", "ccxt", "os.environ", "time.time",
                      ".withdraw(", ".transfer("):
        assert forbidden not in source
