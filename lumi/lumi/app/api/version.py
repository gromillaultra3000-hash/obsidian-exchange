from fastapi import APIRouter
from lumi.app.version.metadata import MODULE_NAME, VERSION, BUILD_NAME, BUILD_STAGE, API_VERSION, CAPABILITIES

router = APIRouter()


@router.get("/version")
async def version():
    return {
        "moduleName": MODULE_NAME,
        "version": VERSION,
        "buildName": BUILD_NAME,
        "buildStage": BUILD_STAGE,
        "apiVersion": API_VERSION,
        "capabilities": CAPABILITIES,
        "status": "ok",
    }
