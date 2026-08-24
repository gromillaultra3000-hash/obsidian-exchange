import uuid
from fastapi import APIRouter, HTTPException, Query
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.sandbox import SandboxWorkspaceRequest, SandboxTestRunRequest, ApplyPreparationRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/sandbox", tags=["sandbox"])

@router.post("/workspaces")
async def create_workspace(request: SandboxWorkspaceRequest):
    try:
        return runtime_instance.create_sandbox_workspace(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="WORKSPACE_CREATION_ERROR", message=str(exc)).model_dump())

@router.get("/workspaces")
async def list_workspaces(projectId: str = None):
    return runtime_instance.list_sandbox_workspaces(projectId)

@router.get("/workspaces/{workspaceId}")
async def get_workspace(workspaceId: str):
    workspace = runtime_instance.get_sandbox_workspace(workspaceId)
    if not workspace:
        raise HTTPException(status_code=404, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="WORKSPACE_NOT_FOUND", message=f"Workspace {workspaceId} not found").model_dump())
    return workspace

@router.post("/workspaces/{workspaceId}/discard")
async def discard_workspace(workspaceId: str):
    workspace = runtime_instance.discard_sandbox_workspace(workspaceId)
    if not workspace:
        raise HTTPException(status_code=404, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="WORKSPACE_NOT_FOUND", message=f"Workspace {workspaceId} not found").model_dump())
    return workspace

@router.post("/workspaces/{workspaceId}/apply-diff-preview/{diffPreviewId}")
async def apply_diff_preview(workspaceId: str, diffPreviewId: str):
    try:
        return runtime_instance.apply_patch_preview_to_sandbox(workspaceId, diffPreviewId)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="APPLY_PREVIEW_ERROR", message=str(exc)).model_dump())

@router.post("/tests/run")
async def run_tests(request: SandboxTestRunRequest):
    try:
        return runtime_instance.run_sandbox_tests(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="TEST_RUN_ERROR", message=str(exc)).model_dump())

@router.get("/tests/results")
async def list_test_results(projectId: str = None):
    return runtime_instance.list_sandbox_test_results(projectId)

@router.get("/tests/results/{testRunResultId}")
async def get_test_result(testRunResultId: str):
    result = runtime_instance.get_sandbox_test_result(testRunResultId)
    if not result:
        raise HTTPException(status_code=404, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="TEST_RESULT_NOT_FOUND", message=f"Test result {testRunResultId} not found").model_dump())
    return result

@router.post("/apply/prepare")
async def prepare_apply(request: ApplyPreparationRequest):
    try:
        return runtime_instance.prepare_apply_package(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="APPLY_PREPARE_ERROR", message=str(exc)).model_dump())

@router.get("/apply/packages")
async def list_apply_packages(projectId: str = None):
    return runtime_instance.list_apply_packages(projectId)

@router.get("/apply/packages/{applyPackageId}")
async def get_apply_package(applyPackageId: str):
    package = runtime_instance.get_apply_package(applyPackageId)
    if not package:
        raise HTTPException(status_code=404, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code="APPLY_PACKAGE_NOT_FOUND", message=f"Apply package {applyPackageId} not found").model_dump())
    return package

@router.get("/command-guard/check")
async def check_command(command: str = Query(...), projectType: str = Query(None)):
    return runtime_instance.check_command(command, projectType)
