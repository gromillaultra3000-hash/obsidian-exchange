import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
KAIROS_ROOT = ROOT / "kairos"
for path in (str(KAIROS_ROOT), str(ROOT / "lumi"), str(ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

from app.evidence_contracts import HardVerdict, build_evidence
from app.shadow_advisory_wire import AdvisoryResponse, build_request, dispatch
from lumi.app.integration.shadow_advisory import evaluate, validate_request

NOW = datetime(2026, 8, 11, 4, 0, tzinfo=timezone.utc)


def make_request(*, hard=HardVerdict.ALLOW, signal="CONNECTOR_DEGRADED",
                 facts=None, freshness="FRESH"):
    evidence = build_evidence(
        observed_at=NOW, subject_kind="CONNECTOR_HEALTH", signal_type=signal,
        source_class="DETERMINISTIC", freshness=freshness,
        facts=facts or {"failure_count": 0, "reachable": True})
    return build_request(
        requested_at=NOW + timedelta(seconds=1), hard_verdict=hard,
        evidence=[evidence])


def test_frozen_request_evaluates_to_exact_frozen_response():
    request = json.loads((ROOT / "contracts/e2-shadow/advisory-request.v1.json").read_text())
    expected = json.loads((ROOT / "contracts/e2-shadow/advisory-response.v1.json").read_text())
    assert evaluate(request, evaluated_at=NOW + timedelta(seconds=2)) == expected
    assert AdvisoryResponse.model_validate(expected).requestId == request["requestId"]


@pytest.mark.parametrize(("signal", "facts", "expected"), [
    ("PERMISSION_DRIFT", {"permission_valid": False, "withdrawal_enabled": True}, "FREEZE"),
    ("CONNECTOR_DEGRADED", {"failure_count": 2, "reachable": False}, "HOLD"),
    ("CONNECTOR_DEGRADED", {"failure_count": 3, "reachable": False}, "MANUAL"),
    ("PROVIDER_RATE_LIMIT", {"rate_limited": True, "retry_bucket": "LT_1M"}, "HOLD"),
    ("MARKET_DATA_STALE", {"age_bucket": "S60_299", "source_count": 2}, "HOLD"),
])
def test_deterministic_rules_only_tighten(signal, facts, expected):
    request = make_request(signal=signal, facts=facts)
    response = evaluate(
        request.model_dump(mode="json"), evaluated_at=NOW + timedelta(seconds=2))
    assert response["advisoryVerdict"] == expected
    assert "actionAllowed" not in response and "execution" not in json.dumps(response).lower()


def test_hard_freeze_is_an_independent_floor_even_for_healthy_evidence():
    request = make_request(hard=HardVerdict.FREEZE)
    response = evaluate(
        request.model_dump(mode="json"), evaluated_at=NOW + timedelta(seconds=2))
    assert response["advisoryVerdict"] == "FREEZE"
    assert "HARD_FLOOR_APPLIED" in response["reasonCodes"]


def test_cross_package_request_response_dispatch_is_non_executing():
    request = make_request(
        signal="CONNECTOR_DEGRADED", facts={"failure_count": 3, "reachable": False})
    def transport(payload, timeout):
        assert timeout == 0.75
        return evaluate(payload, evaluated_at=NOW + timedelta(seconds=2))
    result = dispatch(
        request, transport=transport, decided_at=NOW + timedelta(seconds=3))
    assert result == {
        "schemaVersion": "shadow-advisory-dispatch.v1",
        "requestId": request.requestId, "status": "OK",
        "advisoryVerdict": "MANUAL", "combinedVerdict": "MANUAL",
        "reasonCodes": ["HARD_GATE_APPLIED", "ADVISORY_TIGHTENED"],
        "modelVersion": "lumi-shadow-rules-v1",
        "executionEffect": "NONE", "actionAllowed": False,
    }


@pytest.mark.parametrize("mutation", [
    {"extra": "field"},
    {"requestId": "ar_" + "0" * 64},
    {"hardVerdict": "BUY"},
])
def test_request_field_hash_or_enum_drift_fails_lumi_validation(mutation):
    value = make_request().model_dump(mode="json")
    value.update(mutation)
    with pytest.raises(ValueError):
        validate_request(value)


def test_private_fact_mutation_fails_before_request_hash_check():
    value = make_request().model_dump(mode="json")
    value["evidence"][0]["facts"]["account_id"] = 7
    with pytest.raises(ValueError, match="privacy"):
        validate_request(value)


@pytest.mark.parametrize(("signal", "facts", "message"), [
    ("UNFROZEN_SIGNAL", {"failure_count": 0, "reachable": True}, "catalog"),
    ("CONNECTOR_DEGRADED", {"failure_count": "3", "reachable": False}, "buckets"),
    ("CONNECTOR_DEGRADED", {"failure_count": -1, "reachable": False}, "buckets"),
    ("ADVISORY_UNAVAILABLE", {"failure_class": "TIMEOUT", "latency_bucket": "712ms"},
     "buckets"),
])
def test_trigger_specific_fact_types_and_buckets_are_independently_frozen(
        signal, facts, message):
    value = make_request(signal=signal, facts=facts).model_dump(mode="json")
    with pytest.raises(ValueError, match=message):
        validate_request(value)


def test_adapter_has_no_route_network_model_token_or_state_surface():
    source = (
        ROOT / "lumi/lumi/app/integration/shadow_advisory.py").read_text().lower()
    assert all(term not in source for term in (
        "fastapi", "router", "urllib", "requests", "http://", "https://",
        "token", "provider_runtime", "model.invoke", "open(", "write_text", "write_bytes"))
