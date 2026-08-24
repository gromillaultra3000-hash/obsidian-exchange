from typing import List, Dict, Any
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.roles.role_catalog import get_role
from lumi.app.capabilities.capability_profile import CapabilityProfile


class RoleMatcher:
    def __init__(self):
        self.capability_profile = CapabilityProfile()

    def provider_role_score(self, provider: ProviderProfile, role_id: str) -> Dict[str, Any]:
        role = get_role(role_id)
        if not role:
            return {"providerId": provider.providerId, "roleId": role_id, "score": 0.0, "matched": False, "missingCapabilities": ["unknown_role"]}
        provider_caps = set(self.capability_profile.normalize_capabilities(provider.capabilities))
        required_caps = set(role.get("requiredCapabilities", []))
        matched = provider_caps & required_caps
        assigned_bonus = 0.25 if role_id in provider.roles else 0.0
        score = (len(matched) / len(required_caps) if required_caps else 1.0) + assigned_bonus
        score = min(score, 1.0)
        return {
            "providerId": provider.providerId,
            "roleId": role_id,
            "score": round(score, 4),
            "matched": len(matched) == len(required_caps),
            "assigned": role_id in provider.roles,
            "missingCapabilities": sorted(required_caps - provider_caps),
        }

    def match_providers_to_roles(self, providers: List[ProviderProfile], required_roles: List[str]) -> List[Dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for provider in providers:
            for role_id in required_roles:
                results.append(self.provider_role_score(provider, role_id))
        return sorted(results, key=lambda item: item["score"], reverse=True)
