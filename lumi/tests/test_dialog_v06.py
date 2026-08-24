from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def _create_session(title="Dialog Test"):
    resp = client.post("/dialog/sessions", json={"title": title, "hostAppId": "test_host", "userId": "u1"})
    assert resp.status_code == 200
    return resp.json()["sessionId"]


def _register_provider(pid="dialog-v06", notes="valid_with_evidence"):
    return client.post("/providers", json={"providerId": pid, "displayName": pid, "providerType": "mock", "apiFormat": "json", "enabled": True, "capabilities": ["text_reasoning"], "roles": ["reviewer"], "costProfile": {}, "latencyProfile": {}, "reliabilityScore": 0.9, "notes": notes})


def test_create_list_close_session():
    sid = _create_session()
    assert client.get(f"/dialog/sessions/{sid}").json()["status"] == "active"
    assert client.get("/dialog/sessions").json()
    closed = client.post(f"/dialog/sessions/{sid}/close").json()
    assert closed["status"] == "closed"


def test_dialog_message_creates_decision_and_messages():
    sid = _create_session()
    _register_provider()
    response = client.post(f"/dialog/sessions/{sid}/message", json={"text": "Analyze this request safely"})
    assert response.status_code == 200
    data = response.json()
    assert data["decisionId"]
    assert data["shortAnswer"]
    assert data["routeSummary"] is not None
    messages = client.get(f"/dialog/sessions/{sid}/messages").json()
    assert len(messages) >= 2
    session = client.get(f"/dialog/sessions/{sid}").json()
    assert data["decisionId"] in session["linkedDecisionIds"]


def test_dialog_show_status_history_and_explain():
    sid = _create_session()
    _register_provider("dialog-v06-2")
    client.post(f"/dialog/sessions/{sid}/message", json={"text": "First normal request"})
    status = client.post(f"/dialog/sessions/{sid}/message", json={"text": "статус"}).json()
    assert status["commandType"] == "show_status"
    history = client.post(f"/dialog/sessions/{sid}/message", json={"text": "покажи историю"}).json()
    assert history["commandType"] == "show_history"
    explain = client.post(f"/dialog/sessions/{sid}/message", json={"text": "объясни решение"}).json()
    assert explain["commandType"] == "explain_decision"
    assert explain["shortAnswer"]


def test_closed_session_returns_closed_response():
    sid = _create_session()
    client.post(f"/dialog/sessions/{sid}/close")
    data = client.post(f"/dialog/sessions/{sid}/message", json={"text": "test"}).json()
    assert "closed" in data["shortAnswer"].lower() or "closed" in data["text"].lower()


def test_dialog_secret_redaction():
    sid = _create_session()
    _register_provider("dialog-secret")
    client.post(f"/dialog/sessions/{sid}/message", json={"text": "Please analyze api_key=sk-test-secret-value"})
    messages = client.get(f"/dialog/sessions/{sid}/messages").json()
    assert "sk-test-secret-value" not in str(messages)
    assert "***REDACTED***" in str(messages)
