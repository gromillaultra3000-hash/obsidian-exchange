from typing import List
from lumi.app.core.errors import ProviderNotFoundError, ProviderDuplicateError, InvalidProviderConfigError
from lumi.app.schemas.provider import ProviderProfile


class ProviderRegistry:
    def __init__(self):
        self._providers: dict[str, ProviderProfile] = {}

    def add_provider(self, profile: ProviderProfile):
        if profile.providerId in self._providers:
            raise ProviderDuplicateError(profile.providerId)
        if not profile.providerId or not profile.providerType or not profile.apiFormat:
            raise InvalidProviderConfigError({"reason": "missing_required_provider_fields"})
        self._providers[profile.providerId] = profile

    def update_provider(self, provider_id: str, patch: dict) -> ProviderProfile:
        if provider_id not in self._providers:
            raise ProviderNotFoundError(provider_id)
        current = self._providers[provider_id].model_dump()
        current.update(patch)
        updated = ProviderProfile(**current)
        self._providers[provider_id] = updated
        return updated

    def disable_provider(self, provider_id: str) -> ProviderProfile:
        if provider_id not in self._providers:
            raise ProviderNotFoundError(provider_id)
        current = self._providers[provider_id].model_dump()
        current["enabled"] = False
        self._providers[provider_id] = ProviderProfile(**current)
        return self._providers[provider_id]

    def enable_provider(self, provider_id: str) -> ProviderProfile:
        if provider_id not in self._providers:
            raise ProviderNotFoundError(provider_id)
        current = self._providers[provider_id].model_dump()
        current["enabled"] = True
        self._providers[provider_id] = ProviderProfile(**current)
        return self._providers[provider_id]

    def get_provider(self, provider_id: str) -> ProviderProfile:
        if provider_id not in self._providers:
            raise ProviderNotFoundError(provider_id)
        return self._providers[provider_id]

    def list_providers(self) -> List[ProviderProfile]:
        return list(self._providers.values())

    def list_enabled_providers(self) -> List[ProviderProfile]:
        return [p for p in self._providers.values() if p.enabled]

    def provider_exists(self, provider_id: str) -> bool:
        return provider_id in self._providers

    def clear_for_tests(self):
        self._providers.clear()
