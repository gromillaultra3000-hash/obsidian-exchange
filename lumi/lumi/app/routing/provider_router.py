import uuid
from typing import List
from lumi.app.schemas.task import TaskRequest
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.schemas.routing import TaskClassification, TaskRequirements, RoutePlan
from lumi.app.providers.registry import ProviderRegistry
from lumi.app.audit.audit_log import AuditLog
from lumi.app.capabilities.capability_matcher import CapabilityMatcher
from lumi.app.roles.role_matcher import RoleMatcher


class ProviderRouter:
    def __init__(self, registry: ProviderRegistry, audit_log: AuditLog):
        self.registry = registry
        self.audit_log = audit_log
        self.capability_matcher = CapabilityMatcher()
        self.role_matcher = RoleMatcher()

    def build_route(self, task_request: TaskRequest, requirements: TaskRequirements, classification: TaskClassification) -> RoutePlan:
        route_id = str(uuid.uuid4())
        task_id = task_request.taskId or "unknown"
        enabled_providers = self.registry.list_enabled_providers()
        if not enabled_providers:
            plan = self._create_no_route_plan(route_id, task_id, requirements, "No enabled providers available")
            self._audit_route(plan, task_id)
            return plan

        fallback_providers = [p for p in enabled_providers if self._is_fallback_provider(p)]
        primary_providers = [p for p in enabled_providers if not self._is_fallback_provider(p)]
        selected: list[ProviderProfile] = []
        selected_roles: dict[str, list[str]] = {}
        covered_caps: set[str] = set()
        covered_roles: set[str] = set()

        candidates = self._rank_providers(primary_providers, requirements)
        for provider in candidates:
            if len(selected) >= requirements.maxProviders:
                break
            provider_caps = set(self._normalize(provider.capabilities))
            assigned_roles = set(self._normalize(provider.roles))
            cap_gain = provider_caps & set(requirements.requiredCapabilities)
            role_fit = {role for role in requirements.requiredRoles if self.role_matcher.provider_role_score(provider, role)["matched"]}
            direct_role = assigned_roles & set(requirements.requiredRoles)
            role_gain = role_fit | direct_role
            if cap_gain or role_gain:
                selected.append(provider)
                selected_roles[provider.providerId] = sorted(role_gain or direct_role)
                covered_caps |= cap_gain
                covered_roles |= role_gain

        missing_caps = sorted(set(requirements.requiredCapabilities) - covered_caps)
        missing_roles = sorted(set(requirements.requiredRoles) - covered_roles)
        selected_ids = [p.providerId for p in selected]
        warnings: list[str] = []

        # v0.1 compatibility: a generic mock provider must still support the old smoke /resolve path.
        if not selected_ids:
            legacy_mock_candidates = [p for p in primary_providers if "mock" in self._normalize(p.capabilities)]
            if legacy_mock_candidates:
                legacy = sorted(legacy_mock_candidates, key=lambda p: p.reliabilityScore, reverse=True)[0]
                selected.append(legacy)
                selected_ids.append(legacy.providerId)
                selected_roles[legacy.providerId] = list(legacy.roles or ["reviewer"])
                missing_caps = []
                missing_roles = []
                warnings.append("legacy_mock_provider_route_used")

        route_status = self._determine_route_status(selected_ids, missing_caps, missing_roles, requirements, fallback_providers)
        if "legacy_mock_provider_route_used" in warnings:
            route_status = "READY"
        strategy = self._determine_strategy(selected_ids)
        fallback_used = False

        if route_status in {"PARTIAL", "NO_ROUTE", "BLOCKED"} and requirements.allowFallback and fallback_providers:
            fallback = sorted(fallback_providers, key=lambda p: p.reliabilityScore, reverse=True)[0]
            if fallback.providerId not in selected_ids:
                selected.append(fallback)
                selected_ids.append(fallback.providerId)
            selected_roles[fallback.providerId] = ["fallback_provider"]
            fallback_used = True
            route_status = "FALLBACK"
            strategy = "fallback_only"
            warnings.append("Fallback provider selected because primary route was incomplete")

        if route_status == "READY" and len(selected_ids) < requirements.minProviders and "legacy_mock_provider_route_used" not in warnings:
            route_status = "PARTIAL"
            warnings.append("Selected provider count is below minProviders")

        if fallback_used:
            missing_caps_for_output: list[str] = []
            missing_roles_for_output: list[str] = []
        else:
            missing_caps_for_output = missing_caps
            missing_roles_for_output = missing_roles

        plan = RoutePlan(
            routeId=route_id,
            taskId=task_id,
            taskClass=classification.taskClass,
            selectedProviders=selected_ids,
            selectedProviderRoles=selected_roles,
            requiredCapabilities=list(requirements.requiredCapabilities),
            missingCapabilities=missing_caps_for_output,
            requiredRoles=list(requirements.requiredRoles),
            missingRoles=missing_roles_for_output,
            strategy=strategy,
            minProviders=requirements.minProviders,
            fallbackUsed=fallback_used,
            routeStatus=route_status,
            reason=self._get_reason(route_status, missing_caps, missing_roles, fallback_used),
            warnings=warnings,
            metadata={
                "classification": classification.model_dump(),
                "requirements": requirements.model_dump(),
                "totalProvidersConsidered": len(enabled_providers),
                "primaryProvidersAvailable": len(primary_providers),
                "fallbackProvidersAvailable": len(fallback_providers),
            },
        )
        self._audit_route(plan, task_id)
        return plan

    def _rank_providers(self, providers: List[ProviderProfile], requirements: TaskRequirements) -> List[ProviderProfile]:
        capability_matches = self.capability_matcher.find_best_match(providers, requirements.requiredCapabilities, requirements.optionalCapabilities)
        score_by_provider = {m["providerId"]: m["totalScore"] for m in capability_matches}
        return sorted(providers, key=lambda p: (score_by_provider.get(p.providerId, 0), p.reliabilityScore), reverse=True)

    def _is_fallback_provider(self, provider: ProviderProfile) -> bool:
        caps = set(self._normalize(provider.capabilities))
        roles = set(self._normalize(provider.roles))
        return "fallback_use" in caps or "fallback_provider" in roles

    def _normalize(self, values: list[str]) -> list[str]:
        return [str(v).strip().lower() for v in values or [] if str(v).strip()]

    def _create_no_route_plan(self, route_id: str, task_id: str, requirements: TaskRequirements, reason: str) -> RoutePlan:
        return RoutePlan(
            routeId=route_id,
            taskId=task_id,
            taskClass=requirements.taskClass,
            requiredCapabilities=list(requirements.requiredCapabilities),
            requiredRoles=list(requirements.requiredRoles),
            strategy="no_route",
            minProviders=requirements.minProviders,
            routeStatus="NO_ROUTE",
            reason=reason,
            warnings=[reason],
            metadata={},
        )

    def _determine_strategy(self, selected_provider_ids: list[str]) -> str:
        if not selected_provider_ids:
            return "no_route"
        if len(selected_provider_ids) == 1:
            return "single_provider"
        return "multi_provider_parallel"

    def _determine_route_status(self, selected_provider_ids: list[str], missing_caps: list[str], missing_roles: list[str], requirements: TaskRequirements, fallback_providers: List[ProviderProfile]) -> str:
        if not selected_provider_ids:
            return "NO_ROUTE"
        if len(selected_provider_ids) >= requirements.minProviders and not missing_caps and not missing_roles:
            return "READY"
        if selected_provider_ids and (missing_caps or missing_roles):
            return "PARTIAL"
        return "BLOCKED"

    def _get_reason(self, route_status: str, missing_caps: list[str], missing_roles: list[str], fallback_used: bool) -> str:
        if route_status == "READY":
            return "All requirements met"
        if route_status == "PARTIAL":
            return f"Partial match: missing capabilities {missing_caps}, missing roles {missing_roles}"
        if route_status == "FALLBACK":
            return "Fallback provider used"
        if route_status == "NO_ROUTE":
            return "No suitable providers found"
        if route_status == "BLOCKED":
            return "Routing blocked due to missing critical requirements"
        return "Unknown status"

    def _audit_route(self, plan: RoutePlan, task_id: str) -> None:
        self.audit_log.add_entry("route_plan_created", task_id=task_id, summary=f"Route {plan.routeId}: {plan.routeStatus} - {plan.strategy}", details={"routePlan": plan.model_dump()})
        for provider_id in plan.selectedProviders:
            self.audit_log.add_entry("provider_selected", task_id=task_id, provider_id=provider_id, summary=f"Provider {provider_id} selected for route {plan.routeId}")
        if plan.routeStatus in {"NO_ROUTE", "BLOCKED"}:
            self.audit_log.add_entry("routing_failed", task_id=task_id, summary=f"Routing failed: {plan.reason}")
        if plan.fallbackUsed:
            self.audit_log.add_entry("fallback_route_used", task_id=task_id, summary=f"Fallback route used for task {task_id}")
