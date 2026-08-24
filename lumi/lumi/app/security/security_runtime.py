import uuid
from datetime import datetime, timezone, timedelta
from lumi.app.schemas.security import SecurityState, SetupPasswordRequest, SetupPasswordResult, UnlockRequest, UnlockResult, LockResult

class SecurityRuntime:
    def __init__(self, config_service, password_hasher, token_manager, encryption_service, vault_storage, secret_vault, auth_guard, audit_log, redaction):
        self.config_service=config_service; self.password_hasher=password_hasher; self.token_manager=token_manager; self.encryption_service=encryption_service; self.vault_storage=vault_storage; self.secret_vault=secret_vault; self.auth_guard=auth_guard; self.audit_log=audit_log; self.redaction=redaction
        self._password_hash=None; self._configured=False; self._unlocked=False; self._failed_attempts=0; self._locked_until=None; self._last_unlock_at=None; self._active_session_id=None

    def initialize(self):
        if self.audit_log: self.audit_log.add_entry("security_status_checked", summary="Security runtime initialized")

    def get_security_state(self) -> SecurityState:
        cfg=self.config_service.get_default_config(); warnings=[]
        if not self._configured: warnings.append("Admin password not configured")
        if not cfg.protectedEndpointsEnabled: warnings.append("Protected endpoint mode is disabled")
        if cfg.encryptionEnabled and not self.encryption_service.is_configured(): warnings.append("Encryption key is not loaded; unlock required for vault operations")
        return SecurityState(status="unlocked" if self._unlocked else ("locked" if self._configured else "not_configured"), mode=cfg.mode, configured=self._configured, unlocked=self._unlocked, activeSessionId=self._active_session_id, failedAttempts=self._failed_attempts, lockedUntil=self._locked_until, vaultEnabled=cfg.vaultEnabled, secretsCount=self.secret_vault.list_secrets().count, lastUnlockAt=self._last_unlock_at, protectedEndpointsEnabled=cfg.protectedEndpointsEnabled, warnings=warnings)

    def setup_password(self, request: SetupPasswordRequest) -> SetupPasswordResult:
        if self.audit_log: self.audit_log.add_entry("security_setup_requested", summary="Security setup requested")
        if self._configured:
            return SetupPasswordResult(configured=True, status="locked", message="Admin password is already configured.")
        if request.password != request.confirmPassword:
            return SetupPasswordResult(configured=False, status="not_configured", message="Passwords do not match.")
        strength=self.password_hasher.validate_password_strength(request.password)
        if not strength["valid"]:
            return SetupPasswordResult(configured=False, status="not_configured", message="; ".join(strength["errors"]), warnings=strength.get("warnings", []))
        self._password_hash=self.password_hasher.hash_password(request.password); self._configured=True; self._unlocked=False
        self.encryption_service.configure_master_key_from_password(request.password, self._password_hash["salt"])
        if self.audit_log: self.audit_log.add_entry("security_password_configured", summary="Admin password configured", details={"warnings": strength.get("warnings", [])})
        return SetupPasswordResult(configured=True, status="locked", message="Admin password configured successfully.", warnings=strength.get("warnings", []))

    def unlock(self, request: UnlockRequest) -> UnlockResult:
        if self.audit_log: self.audit_log.add_entry("security_unlock_requested", summary="Security unlock requested")
        if not self._configured:
            return UnlockResult(unlocked=False, status="not_configured", warnings=["Admin password not configured"])
        if self._locked_until:
            until=datetime.fromisoformat(self._locked_until)
            if datetime.now(timezone.utc) < until:
                return UnlockResult(unlocked=False, status="locked", warnings=["Too many failed attempts. Try again later."])
            self._locked_until=None; self._failed_attempts=0
        if not self.password_hasher.verify_password(request.password, self._password_hash):
            self._failed_attempts += 1
            cfg=self.config_service.get_default_config()
            if self._failed_attempts >= cfg.maxFailedAttempts:
                self._locked_until=(datetime.now(timezone.utc)+timedelta(minutes=cfg.lockoutMinutes)).isoformat(); self._failed_attempts=0
            if self.audit_log: self.audit_log.add_entry("security_unlock_failed", summary="Security unlock failed", details={"failedAttempts": self._failed_attempts})
            return UnlockResult(unlocked=False, status="locked", warnings=["Invalid password"])
        session_id=str(uuid.uuid4()); tok=self.token_manager.create_token(session_id, self.config_service.get_default_config().tokenTtlMinutes)
        self.encryption_service.configure_master_key_from_password(request.password, self._password_hash["salt"])
        self._unlocked=True; self._failed_attempts=0; self._last_unlock_at=datetime.now(timezone.utc).isoformat(); self._active_session_id=session_id
        if self.audit_log: self.audit_log.add_entry("security_unlocked", summary="Security unlocked", details={"sessionId": session_id})
        return UnlockResult(unlocked=True, accessToken=tok["accessToken"], expiresAt=tok["expiresAt"], status="unlocked")

    def lock(self) -> LockResult:
        self.token_manager.revoke_all(); self.encryption_service.clear_key(); self._unlocked=False; self._active_session_id=None
        if self.audit_log: self.audit_log.add_entry("security_locked", summary="Security locked")
        return LockResult(locked=True, status="locked", message="Security locked. All sessions revoked.")
