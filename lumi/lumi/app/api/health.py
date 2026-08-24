from fastapi import APIRouter
from lumi.app.version.metadata import VERSION

router = APIRouter()


@router.get("/health")
async def health():
    return {"status": "ok", "module": "Lumi", "version": VERSION}
