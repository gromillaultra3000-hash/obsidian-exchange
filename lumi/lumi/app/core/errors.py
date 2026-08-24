class LumiError(Exception):
    def __init__(self, code: str, message: str, recoverable: bool = False, details: dict | None = None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.recoverable = recoverable
        self.details = details or {}


class ProviderNotFoundError(LumiError):
    def __init__(self, provider_id: str):
        super().__init__("PROVIDER_NOT_FOUND", f"Provider {provider_id} not found", False, {"providerId": provider_id})


class ProviderDuplicateError(LumiError):
    def __init__(self, provider_id: str):
        super().__init__("PROVIDER_DUPLICATE", f"Provider {provider_id} already exists", False, {"providerId": provider_id})


class InvalidProviderConfigError(LumiError):
    def __init__(self, details: dict | None = None):
        super().__init__("INVALID_PROVIDER_CONFIG", "Provider configuration is invalid", False, details)


class NoEnabledProvidersError(LumiError):
    def __init__(self):
        super().__init__("NO_ENABLED_PROVIDERS", "No enabled providers available", True)


class AuditNotFoundError(LumiError):
    def __init__(self, audit_id: str):
        super().__init__("AUDIT_NOT_FOUND", f"Audit entry {audit_id} not found", False, {"auditId": audit_id})
