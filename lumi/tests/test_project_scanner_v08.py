from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
from lumi.app.project_scanner.static_inspector import StaticInspector
from lumi.app.project_scanner.patch_plan_preview import PatchPlanPreviewBuilder
from lumi.app.schemas.project_scanner import ProjectScanRequest

client = TestClient(app)

def setup_function():
    runtime_instance.reset_for_tests()


def _manifest(project_id="sample_project", modes=None):
    return {
        "projectId": project_id,
        "hostAppId": "sample_host",
        "displayName": "Sample Project",
        "projectType": "python",
        "declaredEntryPoints": [],
        "declaredTestPaths": [],
        "declaredConfigFiles": [],
        "declaredDocs": [],
        "allowedScanModes": modes or ["manifest_only", "snapshot", "static_inspection", "improvement_plan"],
        "metadata": {"source": "test"},
    }


def _snapshots(project_id="sample_project"):
    return [
        {"snapshotId": "main", "projectId": project_id, "path": "app/main.py", "fileName": "main.py", "extension": ".py", "sizeBytes": 600_001, "contentPreview": "# TODO refactor\ndef main(): pass", "isBinary": False},
        {"snapshotId": "env", "projectId": project_id, "path": ".env", "fileName": ".env", "extension": "", "sizeBytes": 20, "contentPreview": "api_key=sk-secret-value", "isBinary": False},
        {"snapshotId": "cache", "projectId": project_id, "path": "__pycache__/x.pyc", "fileName": "x.pyc", "extension": ".pyc", "sizeBytes": 100, "isBinary": True, "contentPreview": "should-not-store"},
    ]


def test_register_project_and_snapshots_and_scan():
    assert client.post("/projects/register", json=_manifest()).status_code == 200
    snap_response = client.post("/projects/sample_project/snapshots", json=_snapshots())
    assert snap_response.status_code == 200
    assert snap_response.json()[1]["contentPreview"] == "***REDACTED***"
    assert snap_response.json()[2]["contentPreview"] is None
    scan = client.post("/projects/scan", json={"projectId": "sample_project", "scanMode": "static_inspection", "includeImprovementPlan": True})
    assert scan.status_code == 200
    data = scan.json()
    assert data["status"] == "completed"
    assert data["inventory"]["filesCount"] == 3
    assert len(data["issues"]) >= 4
    assert data["improvementPlan"] is not None
    assert all(preview["canApply"] is False for preview in data["patchPlanPreviews"])


def test_scan_unknown_disabled_and_no_snapshots_blocked():
    unknown = client.post("/projects/scan", json={"projectId": "missing", "scanMode": "static_inspection"}).json()
    assert unknown["status"] == "blocked"
    client.post("/projects/register", json=_manifest("blocked_project"))
    no_snap = client.post("/projects/scan", json={"projectId": "blocked_project", "scanMode": "static_inspection"}).json()
    assert no_snap["status"] == "blocked"
    client.post("/projects/blocked_project/disable")
    disabled = client.post("/projects/scan", json={"projectId": "blocked_project", "scanMode": "manifest_only"}).json()
    assert disabled["status"] == "blocked"


def test_manifest_only_scan_does_not_require_snapshots():
    client.post("/projects/register", json=_manifest("manifest_project"))
    response = client.post("/projects/manifest_project/scan", json={"projectId": "manifest_project", "scanMode": "manifest_only", "includeImprovementPlan": False})
    assert response.status_code == 200
    assert response.json()["status"] == "completed"
    assert response.json()["inventory"]["filesCount"] == 0


def test_project_scanner_read_endpoints_after_scan():
    client.post("/projects/register", json=_manifest())
    client.post("/projects/sample_project/snapshots", json=_snapshots())
    client.post("/projects/scan", json={"projectId": "sample_project", "scanMode": "static_inspection"})
    assert client.get("/projects/sample_project/inventory").status_code == 200
    assert client.get("/projects/sample_project/issues").status_code == 200
    assert client.get("/projects/sample_project/improvement-plan").status_code == 200


def test_integration_project_events():
    host_manifest = {
        "hostAppId": "host_project_events", "displayName": "Host", "appType": "desktop", "allowedModes": ["rest"],
        "capabilitiesRequested": [], "actionsAllowed": [], "eventsSupported": ["custom"], "callbacks": {}, "metadata": {}
    }
    client.post("/integration/handshake", json={"hostAppId": "host_project_events", "manifest": host_manifest, "connectorMode": "rest"})
    event_manifest = {"eventId": "pm1", "hostAppId": "host_project_events", "eventType": "custom", "payload": {"subtype": "project_manifest", "projectManifest": _manifest("event_project")}}
    assert client.post("/integration/events", json=event_manifest).json()["accepted"] is True
    event_snapshot = {"eventId": "ps1", "hostAppId": "host_project_events", "eventType": "custom", "payload": {"subtype": "project_snapshot", "projectId": "event_project", "snapshots": _snapshots("event_project")}}
    assert client.post("/integration/events", json=event_snapshot).json()["accepted"] is True
    event_scan = {"eventId": "psc1", "hostAppId": "host_project_events", "eventType": "custom", "payload": {"subtype": "project_scan_request", "projectId": "event_project", "scanMode": "static_inspection"}}
    result = client.post("/integration/events", json=event_scan).json()
    assert result["accepted"] is True
    assert result["metadata"]["scanResult"]["status"] == "completed"


def test_dialog_project_scan_requires_project_id_and_runs_with_metadata():
    session_id = client.post("/dialog/sessions", json={"title": "Project Scan"}).json()["sessionId"]
    missing = client.post(f"/dialog/sessions/{session_id}/message", json={"text": "проверь проект"}).json()
    assert missing["commandType"] == "project_scan"
    assert "Project ID required" in missing["text"]
    client.post("/projects/register", json=_manifest("dialog_project"))
    client.post("/projects/dialog_project/snapshots", json=_snapshots("dialog_project"))
    ok = client.post(f"/dialog/sessions/{session_id}/message", json={"text": "проверь проект", "metadata": {"projectId": "dialog_project"}}).json()
    assert ok["commandType"] == "project_scan"
    assert ok["metadata"]["projectScanResult"]["status"] == "completed"


def test_action_gateway_improvement_integration_when_action_registered():
    client.post("/actions/register", json={
        "actionId": "create_patch_preview", "title": "Create Patch Preview", "description": "Preview patch only", "category": "maintenance", "enabled": True,
        "riskLevel": "medium", "requiresApproval": True, "supportsDryRun": True, "supportsRollback": False,
        "inputSchema": {"type": "object"}, "outputSchema": {"type": "object"}, "allowedModes": ["proposal", "dry_run"], "metadata": {}
    })
    client.post("/projects/register", json=_manifest("plan_project"))
    client.post("/projects/plan_project/snapshots", json=_snapshots("plan_project"))
    result = client.post("/projects/scan", json={"projectId": "plan_project", "scanMode": "static_inspection"}).json()
    plan = result["improvementPlan"]
    assert plan["actionGatewayResult"] is not None
    assert plan["actionGatewayResult"]["status"] in ["approval_required", "proposal_created", "blocked"]


def test_static_inspector_detects_documented_issue_types_directly():
    client.post("/projects/register", json=_manifest("direct_project"))
    client.post("/projects/direct_project/snapshots", json=_snapshots("direct_project"))
    client.post("/projects/scan", json={"projectId": "direct_project", "scanMode": "static_inspection"})
    issues = client.get("/projects/direct_project/issues").json()
    titles = " ".join(i["title"] for i in issues).lower()
    assert "secret" in titles
    assert "large" in titles
    assert "todo" in titles


def test_patch_preview_never_allows_apply():
    client.post("/projects/register", json=_manifest("preview_project"))
    client.post("/projects/preview_project/snapshots", json=_snapshots("preview_project"))
    result = client.post("/projects/scan", json={"projectId": "preview_project", "scanMode": "static_inspection"}).json()
    assert result["patchPlanPreviews"]
    assert all(p["canApply"] is False for p in result["patchPlanPreviews"])
    assert all(p["applyBlockedReason"] == "real_file_write_disabled_in_v0_8" for p in result["patchPlanPreviews"])


def test_runtime_status_contains_project_counters():
    client.post("/projects/register", json=_manifest("status_project"))
    status = client.get("/runtime/status").json()
    assert status["projectsCount"] >= 1
    assert "fileSnapshotsCount" in status
    assert "projectScansCount" in status
