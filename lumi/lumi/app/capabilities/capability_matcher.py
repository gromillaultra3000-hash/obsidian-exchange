from typing import List, Dict, Any
from lumi.app.schemas.provider import ProviderProfile
from lumi.app.capabilities.capability_profile import CapabilityProfile


class CapabilityMatcher:
    def __init__(self):
        self.capability_profile = CapabilityProfile()

    def find_best_match(self, providers: List[ProviderProfile], required_capabilities: List[str], optional_capabilities: List[str] | None = None) -> List[Dict[str, Any]]:
        optional_capabilities = optional_capabilities or []
        optional_set = set(self.capability_profile.normalize_capabilities(optional_capabilities))
        results: list[dict[str, Any]] = []
        for provider in providers:
            match = self.capability_profile.match_capabilities(provider, required_capabilities).model_dump()
            provider_caps = set(self.capability_profile.normalize_capabilities(provider.capabilities))
            optional_matched = sorted(provider_caps & optional_set)
            match["optionalMatched"] = optional_matched
            match["totalScore"] = round(match["score"] + (0.1 * len(optional_matched)) + (0.1 * provider.reliabilityScore), 4)
            results.append(match)
        return sorted(results, key=lambda item: item["totalScore"], reverse=True)
