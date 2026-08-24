from fastapi import APIRouter
from lumi.app.capabilities.capability_catalog import get_capability_catalog

router = APIRouter(tags=["capabilities"])


@router.get("/capabilities")
async def get_capabilities():
    return {"capabilities": get_capability_catalog(), "status": "ok"}
