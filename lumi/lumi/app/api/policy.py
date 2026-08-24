import uuid
from fastapi import APIRouter, HTTPException
from lumi.app.core.runtime import runtime_instance
from lumi.app.schemas.policy import PolicyRule, LimitDefinition, PolicyCheckRequest
from lumi.app.schemas.errors import ErrorEnvelope

router = APIRouter(prefix="/policy", tags=["policy"])


def _err(code: str, message: str, status: int = 400):
    raise HTTPException(status_code=status, detail=ErrorEnvelope(errorId=str(uuid.uuid4()), code=code, message=message, redacted=True).model_dump())


@router.get("/rules")
async def list_rules():
    return runtime_instance.list_policies()


@router.get("/summary")
async def policy_summary():
    return runtime_instance.get_policy_summary()


@router.post("/rules")
async def add_rule(rule: PolicyRule):
    try:
        return runtime_instance.add_policy_rule(rule)
    except ValueError as exc:
        _err("POLICY_RULE_EXISTS", str(exc), 409)


@router.post("/rules/{ruleId}/enable")
async def enable_rule(ruleId: str):
    try:
        return runtime_instance.enable_policy_rule(ruleId)
    except ValueError as exc:
        _err("POLICY_RULE_NOT_FOUND", str(exc), 404)


@router.post("/rules/{ruleId}/disable")
async def disable_rule(ruleId: str):
    try:
        return runtime_instance.disable_policy_rule(ruleId)
    except ValueError as exc:
        _err("POLICY_RULE_NOT_FOUND", str(exc), 404)


@router.get("/limits")
async def list_limits():
    return runtime_instance.list_limits()


@router.post("/limits")
async def add_limit(limit: LimitDefinition):
    try:
        return runtime_instance.add_limit(limit)
    except ValueError as exc:
        _err("LIMIT_EXISTS", str(exc), 409)


@router.post("/limits/{limitId}/enable")
async def enable_limit(limitId: str):
    try:
        return runtime_instance.enable_limit(limitId)
    except ValueError as exc:
        _err("LIMIT_NOT_FOUND", str(exc), 404)


@router.post("/limits/{limitId}/disable")
async def disable_limit(limitId: str):
    try:
        return runtime_instance.disable_limit(limitId)
    except ValueError as exc:
        _err("LIMIT_NOT_FOUND", str(exc), 404)


@router.post("/check")
async def check_policy(request: PolicyCheckRequest):
    return runtime_instance.check_policy(request)
