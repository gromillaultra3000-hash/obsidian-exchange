from fastapi import APIRouter
from lumi.app.core.runtime import runtime_instance

router = APIRouter()


@router.get("/runtime/status")
async def runtime_status():
    return runtime_instance.get_status()
