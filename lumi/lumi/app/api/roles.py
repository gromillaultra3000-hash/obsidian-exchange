from fastapi import APIRouter
from lumi.app.roles.role_catalog import get_role_catalog

router = APIRouter(tags=["roles"])


@router.get("/roles")
async def get_roles():
    return {"roles": get_role_catalog(), "status": "ok"}
