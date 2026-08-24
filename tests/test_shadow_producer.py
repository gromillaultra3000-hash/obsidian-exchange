import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from relay.core.shadow_producer import (
    ShadowProducerDisabled, build_submission, submit,
)
import relay.core.shadow_producer as producer

NOW = datetime(2026, 8, 11, 3, 0, tzinfo=timezone.utc)


def fixture():
    return build_submission(
        observed_at=NOW, subject_kind="CONNECTOR_HEALTH",
        signal_type="RELAY_SHADOW_FIXTURE", source_class="DETERMINISTIC",
        freshness="FRESH", facts={"reachable": True, "failure_count": 0},
        hard_verdict="ALLOW", advisory_verdict="HOLD",
        decided_at=NOW + timedelta(seconds=1))


def test_disabled_producer_does_not_read_keys_or_call_network(monkeypatch):
    monkeypatch.setenv("RELAY_E2_SHADOW_PRODUCER_ENABLED", "0")
    monkeypatch.setattr(producer, "signed_request", lambda *a, **k: pytest.fail("called"))
    with pytest.raises(ShadowProducerDisabled):
        submit(fixture(), principal="oe_web_" + "a" * 48)


def test_enabled_fixture_uses_one_exact_scope_and_rejects_execution_effect(monkeypatch):
    captured = {}
    monkeypatch.setenv("RELAY_E2_SHADOW_PRODUCER_ENABLED", "1")
    def fake(method, path, **kwargs):
        captured.update(method=method, path=path, **kwargs)
        return {"schemaVersion": "shadow-submission-result.v1",
                "recordId": "sd_" + "a" * 64, "sequence": 1,
                "recordHash": "b" * 64, "combinedVerdict": "HOLD",
                "actionAllowed": False}
    monkeypatch.setattr(producer, "signed_request", fake)
    result = submit(fixture(), principal="oe_web_" + "a" * 48)
    assert result["actionAllowed"] is False
    assert captured["method"] == "POST"
    assert captured["path"] == "/internal/v1/shadow-decisions"
    assert captured["scope"] == "shadow:write"
    assert captured["timeout"] == 3.0


@pytest.mark.parametrize("facts", [
    {"account_state": "ok"}, {"wallet_hint": "x"},
    {"amount_bucket": 1}, {"email_seen": False},
])
def test_private_fact_classes_are_rejected(facts):
    with pytest.raises(ValueError, match="privacy"):
        build_submission(
            observed_at=NOW, subject_kind="CONNECTOR_HEALTH", signal_type="PRIVATE_FIXTURE",
            source_class="DETERMINISTIC", freshness="FRESH", facts=facts,
            hard_verdict="HOLD", advisory_verdict="ALLOW",
            decided_at=NOW + timedelta(seconds=1))


def test_relay_fixture_is_accepted_by_frozen_kairos_contract():
    kairos_root = ROOT / "kairos"
    if str(kairos_root) not in sys.path:
        sys.path.insert(0, str(kairos_root))
    from app.shadow_ingress import ShadowSubmission
    accepted = ShadowSubmission.model_validate_json(json.dumps(fixture()))
    assert accepted.decision.combinedVerdict.value == "HOLD"


def test_deployed_relay_flag_is_explicitly_disabled():
    dropin = (ROOT / "deploy" / "relay-fastapi-zz-runtime.conf").read_text()
    assert "Environment=RELAY_E2_SHADOW_PRODUCER_ENABLED=0" in dropin
