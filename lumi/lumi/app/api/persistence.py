import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.persistence import PersistenceSaveRequest, PersistenceLoadRequest, ExportSnapshotRequest, ImportSnapshotRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/persistence", tags=["persistence"])

def _err(code, message, status=400):
    raise HTTPException(status_code=status, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message).model_dump())

@router.get("/status")
async def storage_status():
    cfg = runtime_instance.storage_config.get_default_config()
    active = runtime_instance.profile_manager.get_active_profile()
    return {"enabled": cfg.enabled, "backendType": cfg.backendType, "activeProfileId": active.profileId if active else "default", "dataDir": cfg.dataDir, "autoSave": cfg.autoSave, "autoLoad": cfg.autoLoad}

@router.get("/health")
async def storage_health():
    return runtime_instance.get_storage_health()

@router.get("/profiles")
async def list_profiles():
    return runtime_instance.list_profiles()

@router.post("/profiles")
async def create_profile(request: dict):
    try: return runtime_instance.create_profile(request.get("profileId", ""), request.get("displayName"))
    except ValueError as e: _err("PROFILE_ERROR", str(e))

@router.get("/profiles/{profileId}")
async def get_profile(profileId: str):
    profile = runtime_instance.profile_manager.get_profile(profileId)
    if not profile: _err("PROFILE_NOT_FOUND", f"Profile {profileId} not found", 404)
    return profile

@router.post("/profiles/{profileId}/activate")
async def activate_profile(profileId: str):
    try: return runtime_instance.set_active_profile(profileId)
    except ValueError as e: _err("PROFILE_ERROR", str(e))

@router.post("/profiles/{profileId}/reset")
async def reset_profile(profileId: str):
    try: return runtime_instance.reset_profile(profileId)
    except ValueError as e: _err("PROFILE_ERROR", str(e))

@router.post("/save")
async def save_state(request: PersistenceSaveRequest | None = None):
    try: return runtime_instance.save_state(request)
    except Exception as e: _err("SAVE_ERROR", str(e))

@router.post("/load")
async def load_state(request: PersistenceLoadRequest | None = None):
    try: return runtime_instance.load_state(request)
    except Exception as e: _err("LOAD_ERROR", str(e))

@router.post("/export")
async def export_snapshot(request: ExportSnapshotRequest | None = None):
    try: return runtime_instance.export_state_snapshot(request)
    except Exception as e: _err("EXPORT_ERROR", str(e))

@router.post("/import")
async def import_snapshot(request: ImportSnapshotRequest):
    try: return runtime_instance.import_state_snapshot(request)
    except Exception as e: _err("IMPORT_ERROR", str(e))

@router.get("/retention-policy")
async def get_retention_policy():
    return runtime_instance.get_retention_policy()

@router.post("/retention-policy/dry-run")
async def retention_dry_run():
    return runtime_instance.apply_retention_policy(dry_run=True)
