from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def _decision():
    client.post("/providers", json={"providerId": "explain-v06", "displayName": "Explain", "providerType": "mock", "apiFormat": "json", "enabled": True, "capabilities": ["text_reasoning"], "roles": ["reviewer"], "costProfile": {}, "latencyProfile": {}, "reliabilityScore": 0.9, "notes": "valid_with_evidence"})
    return client.post("/resolve", json={"input": "explain this request", "context": {}, "requirements": {}}).json()


def test_human_explanation_api():
    decision = _decision()
    response = client.get(f"/explain/{decision['decisionId']}?mode=human")
    assert response.status_code == 200
    data = response.json()
    assert data["explanation"]["mode"] == "human"
    assert data["explanation"]["shortAnswer"]


def test_technical_explanation_api_with_timeline():
    decision = _decision()
    response = client.get(f"/explain/{decision['decisionId']}?mode=technical&includeTimeline=true")
    assert response.status_code == 200
    data = response.json()
    assert data["explanation"]["mode"] == "technical"
    assert "routing" in data["explanation"]["technicalDetails"]
    assert data["timeline"] is not None


def test_unknown_explanation_returns_404():
    response = client.get("/explain/not-a-real-decision")
    assert response.status_code == 404
