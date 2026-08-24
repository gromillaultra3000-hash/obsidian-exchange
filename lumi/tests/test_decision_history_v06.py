from fastapi.testclient import TestClient
from lumi.app.main import app

client = TestClient(app)


def _register_provider(pid="hist-prov", notes="valid_with_evidence"):
    return client.post("/providers", json={"providerId": pid, "displayName": pid, "providerType": "mock", "apiFormat": "json", "enabled": True, "capabilities": ["text_reasoning"], "roles": ["reviewer"], "costProfile": {}, "latencyProfile": {}, "reliabilityScore": 0.9, "notes": notes})


def test_decision_recorded_after_resolve_and_lookup():
    _register_provider()
    response = client.post("/resolve", json={"input": "history test", "context": {}, "requirements": {}})
    assert response.status_code == 200
    decision = response.json()
    lookup = client.get(f"/history/decisions/{decision['decisionId']}")
    assert lookup.status_code == 200
    record = lookup.json()
    assert record["decisionId"] == decision["decisionId"]
    assert record["taskId"] == decision["taskId"]


def test_history_list_and_query():
    _register_provider("hist-query")
    client.post("/resolve", json={"input": "query test", "context": {}, "requirements": {}})
    listed = client.get("/history/decisions").json()
    assert listed["total"] >= 1
    status = listed["records"][0]["status"]
    queried = client.post("/history/decisions/query", json={"status": status}).json()
    assert queried["total"] >= 1


def test_duplicate_history_not_duplicated():
    _register_provider("hist-dupe")
    decision = client.post("/resolve", json={"input": "dupe test", "context": {}, "requirements": {}}).json()
    before = client.get("/history/decisions").json()["total"]
    # Explanation lookup should not create another history record.
    client.get(f"/explain/{decision['decisionId']}")
    after = client.get("/history/decisions").json()["total"]
    assert after == before


def test_timeline_for_decision():
    _register_provider("hist-timeline")
    decision = client.post("/resolve", json={"input": "timeline test", "context": {}, "requirements": {}}).json()
    timeline = client.get(f"/history/decisions/{decision['decisionId']}/timeline")
    assert timeline.status_code == 200
    data = timeline.json()
    assert data["decisionId"] == decision["decisionId"]
    assert data["events"]
