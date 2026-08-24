from fastapi.testclient import TestClient
from lumi.app.main import app
from lumi.app.core.runtime import runtime_instance

client = TestClient(app)


def setup_function():
    runtime_instance.reset_for_tests()


def register_project(project_id="sandbox_proj"):
    response = client.post("/projects/register", json={
        "projectId": project_id,
        "displayName": "Sandbox Project",
        "projectType": "python",
        "allowedScanModes": ["manifest_only", "snapshot", "static_inspection", "improvement_plan"],
    })
    assert response.status_code == 200
    snap = {
        "snapshotId": f"{project_id}-main",
        "projectId": project_id,
        "path": "main.py",
        "fileName": "main.py",
        "extension": ".py",
        "sizeBytes": 120,
        "contentPreview": "print('safe')\n",
        "isBinary": False,
        "isGenerated": False,
    }
    assert client.post(f"/projects/{project_id}/snapshots", json=[snap]).status_code == 200
    return project_id


def create_patch(project_id):
    response = client.post("/patches/plan", json={
        "projectId": project_id,
        "source": "manual",
        "title": "Prepare docs patch",
        "summary": "Preview documentation update.",
        "targetFiles": ["README.md"],
        "requestedChanges": [{"changeType": "docs_change", "description": "Add README structure."}],
        "riskLevel": "low",
    })
    assert response.status_code == 200
    data = response.json()
    assert data["diffPreview"]["canApply"] is False
    return data


def test_sandbox_workspace_created_from_snapshots():
    project_id = register_project()
    response = client.post("/sandbox/workspaces", json={"projectId": project_id, "source": "project_snapshots", "includeSnapshots": True})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ready"
    assert len(data["files"]) == 1


def test_command_guard_blocks_dangerous_commands():
    assert client.get("/sandbox/command-guard/check", params={"command": "pytest -q"}).json()["allowlisted"] is True
    for command in ["rm -rf /", "git status", "pip install x", "curl http://example.com", "python -c print(1)", "pytest -q && rm -rf /"]:
        result = client.get("/sandbox/command-guard/check", params={"command": command}).json()
        assert result["allowlisted"] is False
        assert result["blockedReason"]


def test_sandbox_test_preview_only_does_not_execute():
    project_id = register_project()
    response = client.post("/sandbox/tests/run", json={"projectId": project_id, "commands": ["pytest -q"], "mode": "preview_only"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "completed"
    assert data["commands"][0]["status"] == "allowed"
    assert data["canAffectHost"] is False
    assert data["commands"][0]["exitCode"] is None


def test_controlled_sandbox_is_safely_blocked_when_unavailable():
    project_id = register_project()
    response = client.post("/sandbox/tests/run", json={"projectId": project_id, "commands": ["pytest -q"], "mode": "controlled_sandbox"})
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "blocked"
    assert data["commands"][0]["status"] == "blocked"
    assert "controlled_sandbox_execution_not_available" in data["commands"][0]["blockedReason"]


def test_apply_diff_preview_to_sandbox_never_affects_host():
    project_id = register_project()
    patch = create_patch(project_id)
    workspace = client.post("/sandbox/workspaces", json={"projectId": project_id}).json()
    response = client.post(f"/sandbox/workspaces/{workspace['workspaceId']}/apply-diff-preview/{patch['diffPreview']['diffPreviewId']}")
    assert response.status_code == 200
    data = response.json()
    assert data["canAffectHost"] is False
    assert data["hostWriteBlockedReason"] == "host_project_write_disabled_in_v1_0"


def test_apply_preparation_package_never_applies_to_host():
    project_id = register_project()
    patch = create_patch(project_id)
    response = client.post("/sandbox/apply/prepare", json={"projectId": project_id, "patchPlanResultId": patch["resultId"], "diffPreviewId": patch["diffPreview"]["diffPreviewId"], "rollbackMetadataId": patch["rollbackMetadata"]["rollbackMetadataId"]})
    assert response.status_code == 200
    data = response.json()
    assert data["canApplyToHost"] is False
    assert data["approvalRequired"] is True
    assert data["rollbackAvailable"] is True


def test_unknown_project_workspace_fails_closed():
    response = client.post("/sandbox/workspaces", json={"projectId": "missing"})
    assert response.status_code == 400


def test_integration_sandbox_events():
    # Host must be registered first.
    client.post("/integration/handshake", json={
        "hostAppId": "host1",
        "connectorMode": "rest",
        "manifest": {"hostAppId": "host1", "displayName": "Host 1", "appType": "desktop", "allowedModes": ["rest"], "capabilitiesRequested": [], "actionsAllowed": [], "eventsSupported": ["custom"], "callbacks": {}, "metadata": {}},
    })
    project_id = register_project("event_proj")
    event = {"eventId": "evt-sandbox", "hostAppId": "host1", "eventType": "custom", "payload": {"subtype": "sandbox_workspace_request", "projectId": project_id}}
    response = client.post("/integration/events", json=event)
    assert response.status_code == 200
    data = response.json()
    assert data["accepted"] is True
    assert data["metadata"]["workspace"]["status"] == "ready"
