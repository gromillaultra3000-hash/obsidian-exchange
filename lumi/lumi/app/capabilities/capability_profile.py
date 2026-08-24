from typing import List, Dict, Any
from lumi.app.capabilities.capability_catalog import get_capability_catalog, get_capability, known_capability_ids
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.schemas.capabilities import CapabilityMatchResult


class CapabilityProfile:
    def __init__(self):
        self.catalog = get_capability_catalog()
        self.known_capability_ids = known_capability_ids()

    def normalize_capabilities(self, capabilities: List[str]) -> List[str]:
        normalized: list[str] = []
        seen: set[str] = set()
        for cap in capabilities or []:
            clean = str(cap).strip().lower()
            if clean and clean not in seen:
                normalized.append(clean)
                seen.add(clean)
        return normalized

    def check_capabilities(self, capabilities: List[str]) -> Dict[str, Any]:
        normalized = self.normalize_capabilities(capabilities)
        known = [cap for cap in normalized if cap in self.known_capability_ids]
        unknown = [cap for cap in normalized if cap not in self.known_capability_ids]
        return {"knownCapabilities": known, "unknownCapabilities": unknown, "hasUnknown": bool(unknown)}

    def get_capability_score(self, provider: ProviderProfile) -> float:
        known_caps = self.check_capabilities(provider.capabilities)["knownCapabilities"]
        if not known_caps:
            return 0.0
        total_weight = sum(float(get_capability(cap).get("defaultWeight", 0)) for cap in known_caps)
        max_weight = sum(float(cap["defaultWeight"]) for cap in self.catalog)
        return round(min(total_weight / max_weight, 1.0), 4) if max_weight else 0.0

    def match_capabilities(self, provider: ProviderProfile, required_capabilities: List[str]) -> CapabilityMatchResult:
        provider_caps = set(self.normalize_capabilities(provider.capabilities))
        required = set(self.normalize_capabilities(required_capabilities))
        matched = sorted(provider_caps & required)
        missing = sorted(required - provider_caps)
        unknown_provider = sorted(provider_caps - self.known_capability_ids)
        score = len(matched) / len(required) if required else 1.0
        eligible = len(missing) == 0
        return CapabilityMatchResult(
            providerId=provider.providerId,
            requiredCapabilities=sorted(required),
            matchedCapabilities=matched,
            missingCapabilities=missing,
            unknownCapabilities=unknown_provider,
            score=round(score, 4),
            eligible=eligible,
            reason="All capabilities matched" if eligible else f"Missing capabilities: {missing}",
        )
