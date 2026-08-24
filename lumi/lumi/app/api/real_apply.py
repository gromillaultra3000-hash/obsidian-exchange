from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.real_apply import RegisterWorkspaceRequest, ApplyGateRequest, ApplyExecutionRequest, RollbackRequest, BackupPlanRequest
from lumi.app.schemas.errors import ErrorEnvelope
import uuid

router = APIRouter(prefix="/real-apply", tags=["real_apply"])

def _not_found(code, message):
    return HTTPException(status_code=404, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, recoverable=True, redacted=True).model_dump())

@router.get("/config")
async def get_config(): return runtime_instance.get_real_apply_config()

@router.post("/config/enable-controlled")
async def enable_controlled(): return runtime_instance.enable_controlled_apply()

@router.post("/config/disable")
async def disable_apply(): return runtime_instance.disable_real_apply()

@router.post("/workspaces")
async def register_workspace(request: RegisterWorkspaceRequest): return runtime_instance.register_safe_workspace(request)

@router.get("/workspaces")
async def list_workspaces(): return runtime_instance.list_safe_workspaces()

@router.get("/workspaces/{workspaceId}")
async def get_workspace(workspaceId: str):
    ws = runtime_instance.get_safe_workspace(workspaceId)
    if not ws: raise _not_found("WORKSPACE_NOT_FOUND", "Workspace not found")
    return ws

@router.post("/workspaces/{workspaceId}/enable-apply")
async def enable_workspace_apply(workspaceId: str):
    ws = runtime_instance.enable_workspace_apply(workspaceId)
    if not ws: raise _not_found("WORKSPACE_NOT_FOUND", "Workspace not found")
    return ws

@router.post("/workspaces/{workspaceId}/disable-apply")
async def disable_workspace_apply(workspaceId: str):
    ws = runtime_instance.disable_workspace_apply(workspaceId)
    if not ws: raise _not_found("WORKSPACE_NOT_FOUND", "Workspace not found")
    return ws

@router.post("/gate/check")
async def check_gate(request: ApplyGateRequest): return runtime_instance.check_real_apply_gate(request)

@router.post("/backups/plan")
async def backup_plan(request: BackupPlanRequest): return runtime_instance.build_real_backup_plan(request.workspaceId, request.fileChanges)

@router.post("/backups/create")
async def create_backup(request: BackupPlanRequest):
    ws = runtime_instance.get_safe_workspace(request.workspaceId)
    if not ws: raise _not_found("WORKSPACE_NOT_FOUND", "Workspace not found")
    return runtime_instance.create_real_backup(request.workspaceId, request.fileChanges)

@router.get("/backups")
async def list_backups(workspaceId: str | None = None): return runtime_instance.list_real_backups(workspaceId)

@router.get("/backups/{backupId}")
async def get_backup(backupId: str):
    b = runtime_instance.get_real_backup(backupId)
    if not b: raise _not_found("BACKUP_NOT_FOUND", "Backup not found")
    return b

@router.post("/execute")
async def execute_apply(request: ApplyExecutionRequest): return runtime_instance.execute_controlled_apply(request)

@router.get("/results")
async def list_results(): return runtime_instance.list_real_apply_results()

@router.get("/results/{applyId}")
async def get_result(applyId: str):
    r = runtime_instance.get_real_apply_result(applyId)
    if not r: raise _not_found("APPLY_NOT_FOUND", "Apply result not found")
    return r

@router.get("/rollback-packages")
async def list_rollback_packages(workspaceId: str | None = None): return runtime_instance.list_rollback_packages(workspaceId)

@router.get("/rollback-packages/{rollbackPackageId}")
async def get_rollback_package(rollbackPackageId: str):
    pkg = runtime_instance.get_rollback_package(rollbackPackageId)
    if not pkg: raise _not_found("ROLLBACK_NOT_FOUND", "Rollback package not found")
    return pkg

@router.post("/rollback-packages/{rollbackPackageId}/preview")
async def preview_rollback(rollbackPackageId: str):
    preview = runtime_instance.preview_rollback(rollbackPackageId)
    if not preview: raise _not_found("ROLLBACK_NOT_FOUND", "Rollback package not found")
    return preview

@router.post("/rollback")
async def execute_rollback(request: RollbackRequest): return runtime_instance.execute_controlled_rollback(request)
