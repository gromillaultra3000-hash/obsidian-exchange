from fastapi import APIRouter
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.task import TaskRequest

router = APIRouter(prefix="/routing", tags=["routing"])


@router.post("/classify")
async def classify_task(task: TaskRequest):
    return runtime_instance.classify_task(task)


@router.post("/requirements")
async def build_requirements(task: TaskRequest):
    return runtime_instance.build_task_requirements(task)


@router.post("/plan")
async def build_route(task: TaskRequest):
    return runtime_instance.build_route(task)
