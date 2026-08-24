from abc import ABC, abstractmethod
from typing import Dict, Any
from lumi.app.schemas.provider import ProviderProfile, ProviderOutput
from lumi.app.schemas.task import TaskRequest


class ProviderAdapterBase(ABC):
    @abstractmethod
    def validate_config(self, profile: ProviderProfile) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def health_check(self, profile: ProviderProfile) -> Dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def invoke(self, task_request: TaskRequest, profile: ProviderProfile) -> ProviderOutput:
        raise NotImplementedError

    @abstractmethod
    def normalize_output(self, raw_output: Dict[str, Any], profile: ProviderProfile) -> ProviderOutput:
        raise NotImplementedError

    @abstractmethod
    def get_capabilities(self, profile: ProviderProfile) -> list[str]:
        raise NotImplementedError

    @abstractmethod
    def redact_secrets(self, data: Dict[str, Any]) -> Dict[str, Any]:
        raise NotImplementedError
