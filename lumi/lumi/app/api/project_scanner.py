import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.errors import ErrorEnvelope
from lumi.app.schemas.project_scanner import ProjectManifest, FileSnapshot, ProjectScanRequest

router = APIRouter(prefix="/projects", tags=["project_scanner"])


def _http_error(code: str, message: str, status_code: int = 400):
    raise HTTPException(status_code=status_code, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, recoverable=False, details={}, redacted=True).model_dump())

@router.post("/register")
async def register_project(manifest: ProjectManifest):
    validation = runtime_instance.project_manifest_validator.validate_manifest(manifest)
    if not validation["valid"]:
        _http_error("INVALID_PROJECT_MANIFEST", "; ".join(validation["errors"]), 400)
    profile = runtime_instance.register_project(manifest)
    data = profile.model_dump()
    data["warnings"] = validation.get("warnings", [])
    return data

@router.get("")
async def list_projects():
    return runtime_instance.list_projects()

@router.get("/{projectId}")
async def get_project(projectId: str):
    project = runtime_instance.get_project(projectId)
    if not project:
        _http_error("PROJECT_NOT_FOUND", f"Project {projectId} not found", 404)
    return project

@router.post("/{projectId}/enable")
async def enable_project(projectId: str):
    project = runtime_instance.enable_project(projectId)
    if not project:
        _http_error("PROJECT_NOT_FOUND", f"Project {projectId} not found", 404)
    return project

@router.post("/{projectId}/disable")
async def disable_project(projectId: str):
    project = runtime_instance.disable_project(projectId)
    if not project:
        _http_error("PROJECT_NOT_FOUND", f"Project {projectId} not found", 404)
    return project

@router.post("/{projectId}/snapshots")
async def add_snapshots(projectId: str, snapshots: list[FileSnapshot]):
    project = runtime_instance.get_project(projectId)
    if not project:
        _http_error("PROJECT_NOT_FOUND", f"Project {projectId} not found", 404)
    return runtime_instance.add_file_snapshots(projectId, snapshots)

@router.get("/{projectId}/snapshots")
async def list_snapshots(projectId: str):
    project = runtime_instance.get_project(projectId)
    if not project:
        _http_error("PROJECT_NOT_FOUND", f"Project {projectId} not found", 404)
    return runtime_instance.list_file_snapshots(projectId)

@router.post("/scan")
async def scan_project(request: ProjectScanRequest):
    return runtime_instance.scan_project(request)

@router.post("/{projectId}/scan")
async def scan_project_by_id(projectId: str, request: ProjectScanRequest | None = None):
    if request is None:
        request = ProjectScanRequest(projectId=projectId)
    else:
        request.projectId = projectId
    return runtime_instance.scan_project(request)

@router.get("/{projectId}/inventory")
async def get_inventory(projectId: str):
    inventory = runtime_instance.get_project_inventory(projectId)
    if not inventory:
        _http_error("INVENTORY_NOT_FOUND", f"No inventory found for project {projectId}. Run a scan first.", 404)
    return inventory

@router.get("/{projectId}/issues")
async def get_issues(projectId: str):
    if not runtime_instance.get_project(projectId):
        _http_error("PROJECT_NOT_FOUND", f"Project {projectId} not found", 404)
    return runtime_instance.get_project_issues(projectId)

@router.get("/{projectId}/improvement-plan")
async def get_improvement_plan(projectId: str):
    plan = runtime_instance.get_project_improvement_plan(projectId)
    if not plan:
        _http_error("PLAN_NOT_FOUND", f"No improvement plan found for project {projectId}. Run a scan first.", 404)
    return plan
