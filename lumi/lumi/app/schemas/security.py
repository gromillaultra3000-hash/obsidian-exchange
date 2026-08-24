from typing import Optional, List, Dict, Any, Literal
from pydantic import BaseModel, Field

SecurityMode = Literal["compatibility", "protected", "locked"]
SecurityStatus = Literal["not_configured", "locked", "unlocked", "degraded", "disabled"]
SecretStatus = Literal["active", "disabled", "rotated", "deleted"]
SecretKind = Literal["api_key", "token", "password", "client_secret", "webhook_secret", "custom"]

class SecurityConfig(BaseModel):
    enabled: bool = True
    mode: SecurityMode = "compatibility"
    protectedEndpointsEnabled: bool = False
    requireUnlockForUi: bool = False
    tokenTtlMinutes: int = 120
    maxFailedAttempts: int = 10
    lockoutMinutes: int = 15
    vaultEnabled: bool = True
    encryptionEnabled: bool = True
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SecurityState(BaseModel):
    status: SecurityStatus = "not_configured"
    mode: SecurityMode = "compatibility"
    configured: bool = False
    unlocked: bool = False
    activeSessionId: Optional[str] = None
    failedAttempts: int = 0
    lockedUntil: Optional[str] = None
    vaultEnabled: bool = True
    secretsCount: int = 0
    lastUnlockAt: Optional[str] = None
    protectedEndpointsEnabled: bool = False
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SetupPasswordRequest(BaseModel):
    password: str
    confirmPassword: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SetupPasswordResult(BaseModel):
    configured: bool = False
    status: SecurityStatus = "not_configured"
    message: str = ""
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class UnlockRequest(BaseModel):
    password: str
    metadata: Dict[str, Any] = Field(default_factory=dict)

class UnlockResult(BaseModel):
    unlocked: bool = False
    accessToken: Optional[str] = None
    tokenType: str = "Bearer"
    expiresAt: Optional[str] = None
    status: SecurityStatus = "locked"
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class LockResult(BaseModel):
    locked: bool = False
    status: SecurityStatus = "locked"
    message: str = ""

class SecretCreateRequest(BaseModel):
    name: str
    kind: SecretKind = "api_key"
    value: str
    providerId: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SecretUpdateRequest(BaseModel):
    value: Optional[str] = None
    status: Optional[SecretStatus] = None
    labels: Optional[List[str]] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SecretRecord(BaseModel):
    secretId: str
    name: str
    kind: SecretKind = "api_key"
    status: SecretStatus = "active"
    providerId: Optional[str] = None
    secretRef: str = ""
    maskedValue: str = "****"
    createdAt: str = ""
    updatedAt: str = ""
    lastUsedAt: Optional[str] = None
    labels: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SecretValueEnvelope(BaseModel):
    secretId: str
    encryptedValue: str
    algorithm: str = "hmac-xor-stdlib-fallback"
    createdAt: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SecretListResult(BaseModel):
    secrets: List[SecretRecord] = Field(default_factory=list)
    count: int = 0
    redacted: bool = True

class SecretResolveRequest(BaseModel):
    secretRef: str
    purpose: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

class SecretResolveResult(BaseModel):
    resolved: bool = False
    secretRef: str = ""
    secretId: Optional[str] = None
    valueAvailable: bool = False
    maskedValue: Optional[str] = None
    warnings: List[str] = Field(default_factory=list)
    metadata: Dict[str, Any] = Field(default_factory=dict)
