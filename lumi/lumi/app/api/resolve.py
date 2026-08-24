from fastapi import APIRouter
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.task import TaskRequest

router = APIRouter()


@router.post("/resolve")
async def resolve(task: TaskRequest):
    return runtime_instance.resolve(task)
