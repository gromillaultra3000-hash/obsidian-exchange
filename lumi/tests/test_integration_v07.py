import os
import sys
from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance

client = TestClient(app)


def setup_function():
    runtime_instance.reset_for_tests()


def valid_manifest(host_id="host-v07"):
    return {
        "hostAppId": host_id,
        "displayName": "Host V07",
        "appType": "desktop",
        "allowedOrigins": ["localhost"],
        "allowedModes": ["rest", "sidecar"],
        "capabilitiesRequested": ["resolve", "dialog_sessions"],
        "actionsAllowed": ["create_patch_preview"],
        "eventsSupported": ["user_message", "error_log", "action_requested"],
        "callbacks": {"mode": "mock"},
        "metadata": {"source": "test"},
    }


def register_host(host_id="host-v07"):
    manifest = valid_manifest(host_id)
    return client.post("/integration/handshake", json={"hostAppId": host_id, "manifest": manifest, "connectorMode": "rest"})


def register_provider():
    return client.post("/providers", json={
        "providerId": "v07-provider",
        "displayName": "V07 Provider",
        "providerType": "mock",
        "apiFormat": "json",
        "enabled": True,
        "capabilities": ["text_reasoning"],
        "roles": ["reviewer"],
        "costProfile": {},
        "latencyProfile": {},
        "reliabilityScore": 0.9,
        "notes": "valid_with_evidence",
    })


def test_integration_contract_and_sidecar():
    contract = client.get("/integration/contract")
    assert contract.status_code == 200
    data = contract.json()
    assert "rest" in data
    assert any(item["path"] == "/integration/handshake" for item in data["rest"]["requiredEndpoints"])
    sidecar = client.get("/integration/sidecar/status")
    assert sidecar.status_code == 200
    assert sidecar.json()["baseUrl"].startswith("http://127.0.0.1")


def test_valid_handshake_registers_host():
    response = register_host("host-handshake")
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    hosts = client.get("/integration/hosts").json()
    assert any(h["hostAppId"] == "host-handshake" for h in hosts)


def test_invalid_manifest_rejected():
    manifest = {"hostAppId": "", "displayName": "", "appType": "desktop", "allowedModes": [], "capabilitiesRequested": [], "actionsAllowed": [], "eventsSupported": [], "callbacks": {}, "metadata": {}}
    response = client.post("/integration/handshake", json={"hostAppId": "bad", "manifest": manifest, "connectorMode": "rest"})
    assert response.status_code == 200
    assert response.json()["accepted"] is False


def test_disabled_host_event_rejected():
    register_host("host-disabled")
    client.post("/integration/hosts/host-disabled/disable")
    response = client.post("/integration/events", json={"eventId": "e1", "hostAppId": "host-disabled", "eventType": "user_message", "payload": {"text": "hello"}})
    assert response.status_code == 200
    assert response.json()["accepted"] is False


def test_user_message_event_creates_dialog_response():
    register_host("host-user-message")
    register_provider()
    response = client.post("/integration/events", json={"eventId": "e2", "hostAppId": "host-user-message", "eventType": "user_message", "payload": {"text": "Analyze this request"}})
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["dialogResponse"] is not None
    assert data["dialogResponse"].get("decisionId")


def test_error_log_event_creates_decision():
    register_host("host-error")
    register_provider()
    response = client.post("/integration/events", json={"eventId": "e3", "hostAppId": "host-error", "eventType": "error_log", "payload": {"message": "Traceback: sample failure"}})
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["decisionId"]


def test_callback_mock_and_http_blocked():
    register_host("host-callback")
    callback = {"callbackId": "cb1", "hostAppId": "host-callback", "url": "https://example.invalid/cb", "enabled": True, "eventTypes": ["decision_created"], "mode": "mock", "metadata": {}}
    response = client.post("/integration/callbacks/register", json=callback)
    assert response.status_code == 200
    payload = {"callbackId": "cb1", "hostAppId": "host-callback", "decisionId": "d1", "taskId": "t1", "status": "WAIT", "summary": "test"}
    delivered = client.post("/integration/callbacks/mock-deliver", json=payload).json()
    assert delivered["delivered"] is True
    from lumi.app.schemas.integration import DecisionCallbackPayload
    result = runtime_instance.deliver_decision_callback(DecisionCallbackPayload(**payload), mode="http")
    assert result.delivered is False
    assert result.status == "blocked"


def test_python_sdk_imports_and_methods_exist():
    sys.path.insert(0, os.path.abspath("sdk/python"))
    from lumi_client import LumiClient
    c = LumiClient("http://127.0.0.1:8000")
    for name in ["health", "version", "runtime_status", "handshake", "resolve", "create_dialog_session", "send_dialog_message", "propose_action", "approve", "reject", "send_host_event"]:
        assert hasattr(c, name)


def test_secret_redaction_in_manifest_and_event_audit():
    manifest = valid_manifest("host-secret")
    manifest["metadata"] = {"api_key": "sk-secret-value"}
    response = client.post("/integration/handshake", json={"hostAppId": "host-secret", "manifest": manifest, "connectorMode": "rest"})
    assert "sk-secret-value" not in str(response.json())
    client.post("/integration/events", json={"eventId": "e-secret", "hostAppId": "host-secret", "eventType": "custom", "payload": {"token": "secret-token-value"}})
    audit = client.get("/audit").json()
    assert "sk-secret-value" not in str(audit)
    assert "secret-token-value" not in str(audit)
