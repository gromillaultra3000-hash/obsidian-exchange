from pydantic import BaseModel


class RuntimeConfig(BaseModel):
    mode: str = "local"
    log_level: str = "INFO"
    max_providers: int = 20
    audit_enabled: bool = True
    secret_mask: str = "***REDACTED***"
