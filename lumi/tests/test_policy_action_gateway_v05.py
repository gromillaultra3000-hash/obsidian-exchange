from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance

client = TestClient(app)


def setup_function():
    runtime_instance.reset_for_tests()


def register_action(action_id="patch_preview", risk="medium", requires=True, dry=True, modes=None, enabled=True, schema=None):
    payload = {
        "actionId": action_id,
        "title": action_id.replace("_", " ").title(),
        "description": "Test action",
        "category": "test",
        "enabled": enabled,
        "riskLevel": risk,
        "requiresApproval": requires,
        "supportsDryRun": dry,
        "supportsRollback": False,
        "inputSchema": schema or {"type": "object"},
        "outputSchema": {"type": "object"},
        "allowedModes": modes or ["proposal", "dry_run"],
        "metadata": {},
    }
    r = client.post("/actions/register", json=payload)
    assert r.status_code == 200, r.text
    return payload


def test_policy_summary_and_defaults():
    r = client.get("/policy/summary")
    assert r.status_code == 200
    data = r.json()
    assert data["totalRules"] >= 10
    rules = client.get("/policy/rules").json()
    ids = {rule["ruleId"] for rule in rules}
    assert "unknown_action_block" in ids
    assert "execute_mode_blocked_by_default" in ids
    assert "high_risk_requires_approval" in ids


def test_unknown_action_blocked():
    r = client.post("/actions/propose", json={"actionId": "missing", "requestedMode": "proposal"})
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "blocked"
    assert data["policyCheck"]["status"] == "BLOCK"


def test_low_risk_proposal_allowed_but_no_side_effects():
    register_action("read_file", risk="low", requires=False, dry=False, modes=["proposal"])
    r = client.post("/actions/propose", json={"actionId": "read_file", "requestedMode": "proposal", "proposedInput": {"path": "README.md"}})
    data = r.json()
    assert data["status"] == "proposal_created"
    assert data["actionAllowed"] is False
    assert data["approvalRequired"] is False


def test_high_risk_action_creates_approval_prompt():
    register_action("apply_patch", risk="high", requires=True, dry=True, modes=["proposal", "dry_run", "execute"])
    r = client.post("/actions/propose", json={"actionId": "apply_patch", "requestedMode": "proposal", "proposedInput": {"targetFiles": ["a.py"]}})
    data = r.json()
    assert data["status"] == "approval_required"
    assert data["approvalPrompt"] is not None
    assert data["approvalPrompt"]["defaultButton"] == "reject"
    assert "approve" in data["approvalPrompt"]["buttons"]


def test_execute_mode_never_executes_real_action():
    register_action("apply_patch", risk="low", requires=False, dry=True, modes=["proposal", "dry_run", "execute"])
    r = client.post("/actions/propose", json={"actionId": "apply_patch", "requestedMode": "execute", "proposedInput": {"targetFiles": ["a.py"]}})
    data = r.json()
    assert data["status"] in {"blocked", "approval_required"}
    assert data["actionAllowed"] is False


def test_dry_run_ready_only_when_supported():
    register_action("dry_ok", risk="low", requires=False, dry=True, modes=["proposal", "dry_run"])
    data = client.post("/actions/propose", json={"actionId": "dry_ok", "requestedMode": "dry_run"}).json()
    assert data["status"] == "dry_run_ready"
    assert data["actionAllowed"] is True
    register_action("dry_no", risk="low", requires=False, dry=False, modes=["proposal", "dry_run"])
    data2 = client.post("/actions/propose", json={"actionId": "dry_no", "requestedMode": "dry_run"}).json()
    assert data2["status"] == "blocked"


def test_secret_like_input_blocked_and_redacted_in_audit():
    register_action("secret_action", risk="low", requires=False, dry=False, modes=["proposal"])
    data = client.post("/actions/propose", json={"actionId": "secret_action", "requestedMode": "proposal", "proposedInput": {"api_key": "sk-test-secret-123"}}).json()
    assert data["status"] == "blocked"
    assert "sk-test-secret-123" not in str(data)
    audit = client.get("/audit").json()
    assert "sk-test-secret-123" not in str(audit)


def test_approval_decision_recording():
    register_action("critical_action", risk="critical", requires=True, dry=True, modes=["proposal"])
    data = client.post("/actions/propose", json={"actionId": "critical_action", "requestedMode": "proposal"}).json()
    prompt_id = data["approvalPrompt"]["promptId"]
    decision = {"promptId": prompt_id, "decision": "approve", "userId": "tester", "reason": "reviewed"}
    r = client.post(f"/actions/approvals/{prompt_id}/decision", json=decision)
    assert r.status_code == 200
    assert r.json()["decision"] == "approve"
    prompt = client.get(f"/actions/approvals/{prompt_id}").json()
    assert prompt["status"] == "approved"


def test_resolve_with_requested_action_returns_gateway_result():
    client.post("/providers", json={
        "providerId": "p1", "displayName": "P1", "providerType": "mock", "apiFormat": "json", "enabled": True,
        "roles": ["reviewer"], "capabilities": ["text_reasoning"], "costProfile": {}, "latencyProfile": {}, "reliabilityScore": 0.9, "notes": "valid_with_evidence"
    })
    register_action("patch_preview", risk="medium", requires=True, dry=True, modes=["proposal", "dry_run"], schema={"type": "object", "required": ["targetFiles", "changeSummary"]})
    task = {
        "input": "Prepare patch preview",
        "context": {},
        "requirements": {},
        "metadata": {"requestedAction": {"actionId": "patch_preview", "mode": "proposal", "input": {"targetFiles": ["app/main.py"], "changeSummary": "safe preview"}}},
    }
    r = client.post("/resolve", json=task)
    assert r.status_code == 200
    meta = r.json()["metadata"]
    assert "actionGatewayResult" in meta
    assert meta["actionGatewayResult"]["actionId"] == "patch_preview"
    assert "policyCheck" in meta


def test_action_audit_events_exist():
    register_action("audit_action", risk="high", requires=True, dry=True, modes=["proposal"])
    client.post("/actions/propose", json={"actionId": "audit_action", "requestedMode": "proposal"})
    events = [e["eventType"] for e in client.get("/audit").json()]
    assert "action_registered" in events
    assert "policy_check_completed" in events
    assert "action_proposal_created" in events
    assert "approval_prompt_created" in events
