import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.errors import ErrorEnvelope
from lumi.app.schemas.patch_planner import PatchRequest

router = APIRouter(prefix="/patches", tags=["patch_planner"])

def _http_error(code: str, message: str, status_code: int = 400):
    raise HTTPException(status_code=status_code, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, recoverable=False, details={}, redacted=True).model_dump())

@router.post("/plan")
async def plan_patch(request: PatchRequest):
    return runtime_instance.plan_patch(request)

@router.get("/plans")
async def list_patch_plans(projectId: str | None = None):
    return runtime_instance.list_patch_plans(projectId)

@router.get("/plans/{resultId}")
async def get_patch_plan(resultId: str):
    result = runtime_instance.get_patch_plan(resultId)
    if not result:
        _http_error("PATCH_PLAN_NOT_FOUND", f"Patch plan {resultId} not found", 404)
    return result

@router.get("/proposals/{patchProposalId}")
async def get_patch_proposal(patchProposalId: str):
    proposal = runtime_instance.get_patch_proposal(patchProposalId)
    if not proposal:
        _http_error("PATCH_PROPOSAL_NOT_FOUND", f"Patch proposal {patchProposalId} not found", 404)
    return proposal

@router.get("/diff-previews/{diffPreviewId}")
async def get_diff_preview(diffPreviewId: str):
    diff = runtime_instance.get_diff_preview(diffPreviewId)
    if not diff:
        _http_error("DIFF_PREVIEW_NOT_FOUND", f"Diff preview {diffPreviewId} not found", 404)
    return diff

@router.get("/test-plans/{testPlanId}")
async def get_test_plan(testPlanId: str):
    plan = runtime_instance.get_test_plan(testPlanId)
    if not plan:
        _http_error("TEST_PLAN_NOT_FOUND", f"Test plan {testPlanId} not found", 404)
    return plan

@router.get("/test-run-previews/{testRunPreviewId}")
async def get_test_run_preview(testRunPreviewId: str):
    preview = runtime_instance.get_test_run_preview(testRunPreviewId)
    if not preview:
        _http_error("TEST_RUN_PREVIEW_NOT_FOUND", f"Test run preview {testRunPreviewId} not found", 404)
    return preview

@router.get("/rollback-metadata/{rollbackMetadataId}")
async def get_rollback_metadata(rollbackMetadataId: str):
    meta = runtime_instance.get_rollback_metadata(rollbackMetadataId)
    if not meta:
        _http_error("ROLLBACK_METADATA_NOT_FOUND", f"Rollback metadata {rollbackMetadataId} not found", 404)
    return meta

@router.post("/from-project/{projectId}/candidate/{candidateId}")
async def plan_from_candidate(projectId: str, candidateId: str):
    project = runtime_instance.get_project(projectId)
    if not project:
        _http_error("PROJECT_NOT_FOUND", f"Project {projectId} not found", 404)
    issues = runtime_instance.get_project_issues(projectId) or []
    candidate = None
    plan = runtime_instance.get_project_improvement_plan(projectId)
    if plan:
        for item in plan.candidates:
            if item.candidateId == candidateId:
                candidate = item
                break
    if not candidate:
        _http_error("CANDIDATE_NOT_FOUND", f"Candidate {candidateId} not found", 404)
    req = runtime_instance.patch_request_normalizer.from_improvement_candidate(projectId, candidate, issues)
    return runtime_instance.plan_patch(req)

@router.post("/from-project/{projectId}/improvement-plan")
async def plan_from_improvement_plan(projectId: str):
    plan = runtime_instance.get_project_improvement_plan(projectId)
    if not plan:
        _http_error("IMPROVEMENT_PLAN_NOT_FOUND", f"No improvement plan found for project {projectId}", 404)
    req = runtime_instance.patch_request_normalizer.from_improvement_plan(projectId, plan)
    return runtime_instance.plan_patch(req)
