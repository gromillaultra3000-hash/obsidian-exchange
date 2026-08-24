from typing import List
from lumi.app.schemas.policy import PolicyCheckRequest, LimitDefinition


class LimitsChecker:
    def check_limits(self, check_request: PolicyCheckRequest, action_definition=None, limits: List[LimitDefinition] | None = None) -> list[dict]:
        issues: list[dict] = []
        for limit in limits or []:
            if not limit.enabled:
                continue
            if limit.limitId == "allow_execute_mode" and check_request.requestedMode == "execute" and limit.value is False:
                issues.append({"limitId": limit.limitId, "violated": True, "reason": "Execute mode is globally disabled", "severity": "critical"})
            if limit.limitId == "allow_dry_run_mode" and check_request.requestedMode == "dry_run" and limit.value is False:
                issues.append({"limitId": limit.limitId, "violated": True, "reason": "Dry-run mode is globally disabled", "severity": "error"})
            if limit.limitId == "allow_unknown_actions" and action_definition is None and limit.value is False:
                issues.append({"limitId": limit.limitId, "violated": True, "reason": "Unknown actions are not allowed", "severity": "critical"})
            if limit.limitId == "allow_secret_like_action_input" and check_request.metadata.get("containsSecret") and limit.value is False:
                issues.append({"limitId": limit.limitId, "violated": True, "reason": "Secret-like action input is not allowed", "severity": "critical"})
        return issues
