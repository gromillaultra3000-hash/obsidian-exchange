from typing import Dict, Any
from lumi.app.roles.role_catalog import get_role_catalog
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.capabilities.capability_profile import CapabilityProfile


class RoleAssignment:
    def __init__(self):
        self.role_catalog = get_role_catalog()
        self.capability_profile = CapabilityProfile()

    def suggest_roles(self, provider: ProviderProfile) -> Dict[str, Any]:
        provider_caps = set(self.capability_profile.normalize_capabilities(provider.capabilities))
        cap_check = self.capability_profile.check_capabilities(provider.capabilities)
        suggested: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        missing_by_role: dict[str, list[str]] = {}
        score_by_role: dict[str, float] = {}
        for role in self.role_catalog:
            required = set(role.get("requiredCapabilities", []))
            optional = set(role.get("optionalCapabilities", []))
            matched_required = provider_caps & required
            matched_optional = provider_caps & optional
            missing = sorted(required - provider_caps)
            required_score = len(matched_required) / len(required) if required else 0.0
            optional_bonus = min(len(matched_optional) * 0.1, 0.3)
            total_score = round(required_score + optional_bonus, 4)
            role_id = role["roleId"]
            score_by_role[role_id] = total_score
            if not missing:
                suggested.append({"roleId": role_id, "score": total_score})
            else:
                rejected.append({"roleId": role_id, "score": total_score})
                missing_by_role[role_id] = missing
        warnings = []
        if cap_check["unknownCapabilities"]:
            warnings.append(f"Unknown capabilities: {cap_check['unknownCapabilities']}")
        return {
            "providerId": provider.providerId,
            "assignedRoles": list(provider.roles),
            "suggestedRoles": [r["roleId"] for r in sorted(suggested, key=lambda i: i["score"], reverse=True)],
            "rejectedRoles": [r["roleId"] for r in rejected],
            "missingCapabilitiesByRole": missing_by_role,
            "scoreByRole": score_by_role,
            "warnings": warnings,
        }

    def check_role_fit(self, provider: ProviderProfile) -> Dict[str, Any]:
        provider_caps = set(self.capability_profile.normalize_capabilities(provider.capabilities))
        role_fits: list[dict[str, Any]] = []
        for role_id in provider.roles:
            role = next((r for r in self.role_catalog if r["roleId"] == role_id), None)
            if not role:
                role_fits.append({"roleId": role_id, "title": "Unknown", "fitScore": 0.0, "isValid": False, "error": "Role not found in catalog"})
                continue
            required = set(role.get("requiredCapabilities", []))
            optional = set(role.get("optionalCapabilities", []))
            matched_required = sorted(provider_caps & required)
            matched_optional = sorted(provider_caps & optional)
            missing = sorted(required - provider_caps)
            fit_score = len(matched_required) / len(required) if required else 1.0
            role_fits.append({
                "roleId": role_id,
                "title": role["title"],
                "fitScore": round(fit_score, 4),
                "matchedRequired": matched_required,
                "matchedOptional": matched_optional,
                "missingRequired": missing,
                "isValid": not missing,
            })
        return {
            "providerId": provider.providerId,
            "currentRoles": list(provider.roles),
            "capabilities": list(provider.capabilities),
            "roleFits": role_fits,
            "summary": "All roles valid" if role_fits and all(r.get("isValid") for r in role_fits) else "Some roles have missing capabilities",
        }
