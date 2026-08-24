from fastapi.testclient import TestClient
import pytest
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.patch_planner import PatchRequest

client = TestClient(app)

@pytest.fixture(autouse=True)
def reset_runtime():
    runtime_instance.reset_for_tests()


def register_project(project_id="patch-proj", project_type="python"):
    response = client.post("/projects/register", json={
        "projectId": project_id,
        "displayName": "Patch Project",
        "projectType": project_type,
        "allowedScanModes": ["manifest_only", "snapshot", "static_inspection", "improvement_plan"],
    })
    assert response.status_code == 200
    return response.json()


def add_snapshot(project_id="patch-proj", path="README.md", file_name="README.md", preview="hello"):
    response = client.post(f"/projects/{project_id}/snapshots", json=[{
        "snapshotId": "snap-" + file_name.replace('.', '-'),
        "projectId": project_id,
        "path": path,
        "fileName": file_name,
        "extension": ".md" if file_name.endswith(".md") else ".py",
        "sizeBytes": len(preview),
        "contentPreview": preview,
        "isBinary": False,
        "isGenerated": False,
    }])
    assert response.status_code == 200


def test_patch_plan_creates_all_previews():
    register_project()
    add_snapshot()
    response = client.post("/patches/plan", json={
        "projectId": "patch-proj",
        "title": "README preview",
        "summary": "Add docs",
        "targetFiles": ["README.md"],
        "requestedChanges": [{"changeType": "docs_change", "description": "Add README sections"}],
        "riskLevel": "low",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["status"] in ["planned", "preview_ready", "approval_required"]
    assert data["patchProposal"]["canApply"] is False
    assert data["diffPreview"]["canApply"] is False
    assert data["testPlan"]["canExecute"] is False
    assert data["testRunPreview"]["canExecute"] is False
    assert data["rollbackMetadata"]["canRollback"] is False
    assert data["diffPreview"]["totalFilesChanged"] == 1


def test_patch_lookup_endpoints_work():
    register_project()
    add_snapshot()
    data = client.post("/patches/plan", json={
        "projectId": "patch-proj", "title": "README", "summary": "Docs",
        "targetFiles": ["README.md"],
        "requestedChanges": [{"changeType": "docs_change", "description": "Docs"}],
    }).json()
    assert client.get(f"/patches/plans/{data['resultId']}").status_code == 200
    assert client.get(f"/patches/proposals/{data['patchProposal']['patchProposalId']}").status_code == 200
    assert client.get(f"/patches/diff-previews/{data['diffPreview']['diffPreviewId']}").json()["canApply"] is False
    assert client.get(f"/patches/test-plans/{data['testPlan']['testPlanId']}").json()["canExecute"] is False
    assert client.get(f"/patches/test-run-previews/{data['testRunPreview']['testRunPreviewId']}").json()["canExecute"] is False
    assert client.get(f"/patches/rollback-metadata/{data['rollbackMetadata']['rollbackMetadataId']}").json()["canRollback"] is False


def test_patch_safety_blocks_forbidden_paths_and_operations():
    register_project()
    response = client.post("/patches/plan", json={
        "projectId": "patch-proj",
        "title": "Forbidden",
        "summary": "Danger",
        "targetFiles": ["../.env"],
        "requestedChanges": [{"changeType": "delete_file", "description": "delete"}],
    })
    data = response.json()
    assert data["status"] == "blocked"
    assert any("Path traversal" in err or "Forbidden" in err or "Delete" in err for err in data["errors"])


def test_diff_preview_redacts_secret_like_content():
    register_project()
    add_snapshot(preview="api_key=sk-secret123456\nprint('ok')")
    data = client.post("/patches/plan", json={
        "projectId": "patch-proj",
        "title": "Security",
        "summary": "secure",
        "targetFiles": ["README.md"],
        "requestedChanges": [{"changeType": "security_fix", "description": "remove sensitive-looking content"}],
    }).json()
    diff_text = str(data["diffPreview"])
    assert "sk-secret123456" not in diff_text
    assert "***REDACTED***" in diff_text or "REDACTED" in diff_text


def test_dialog_patch_preview_flow():
    register_project()
    add_snapshot()
    session_id = client.post("/dialog/sessions", json={"title": "Patch Dialog"}).json()["sessionId"]
    response = client.post(f"/dialog/sessions/{session_id}/message", json={
        "text": "подготовь патч",
        "metadata": {
            "projectId": "patch-proj",
            "targetFiles": ["README.md"],
            "requestedChanges": [{"changeType": "docs_change", "description": "Add docs"}],
        },
    })
    data = response.json()
    assert data["commandType"] == "patch_preview"
    assert data["metadata"]["diffPreviewId"]
    assert data["metadata"]["canApply"] is False


def test_dialog_patch_preview_requires_project_id():
    session_id = client.post("/dialog/sessions", json={"title": "No Project"}).json()["sessionId"]
    data = client.post(f"/dialog/sessions/{session_id}/message", json={"text": "подготовь патч"}).json()
    assert data["commandType"] == "patch_preview"
    assert "Project ID" in data["text"]


def test_integration_patch_preview_event():
    # Register host first.
    manifest = {
        "hostAppId": "patch-host",
        "displayName": "Patch Host",
        "appType": "desktop",
        "allowedModes": ["rest"],
        "capabilitiesRequested": [],
        "actionsAllowed": [],
        "eventsSupported": ["custom"],
        "callbacks": {},
        "metadata": {},
    }
    assert client.post("/integration/handshake", json={"hostAppId": "patch-host", "manifest": manifest, "connectorMode": "rest"}).json()["accepted"] is True
    register_project(project_id="event-proj")
    add_snapshot(project_id="event-proj")
    event = {
        "eventId": "patch-event-1",
        "hostAppId": "patch-host",
        "eventType": "custom",
        "payload": {
            "subtype": "patch_preview_request",
            "projectId": "event-proj",
            "title": "Patch preview",
            "summary": "Docs",
            "targetFiles": ["README.md"],
            "requestedChanges": [{"changeType": "docs_change", "description": "Docs"}],
        },
    }
    data = client.post("/integration/events", json=event).json()
    assert data["accepted"] is True
    assert data["metadata"]["patchPlanResult"]["diffPreview"]


def test_action_gateway_create_patch_preview_attaches_result():
    register_project()
    add_snapshot()
    action = {
        "actionId": "create_patch_preview",
        "title": "Create Patch Preview",
        "description": "Prepare a patch preview without applying changes",
        "category": "project_maintenance",
        "riskLevel": "medium",
        "requiresApproval": True,
        "supportsDryRun": True,
        "allowedModes": ["proposal", "dry_run"],
        "inputSchema": {"type": "object"},
        "outputSchema": {"type": "object"},
    }
    assert client.post("/actions/register", json=action).status_code == 200
    data = client.post("/patches/plan", json={
        "projectId": "patch-proj",
        "title": "README",
        "summary": "Docs",
        "targetFiles": ["README.md"],
        "requestedChanges": [{"changeType": "docs_change", "description": "Docs"}],
    }).json()
    assert data["patchProposal"]["actionGatewayResult"] is not None
    assert data["patchProposal"]["canApply"] is False
