class AuthGuard:
    def __init__(self, config_service, token_manager, audit_log=None):
        self.config_service=config_service; self.token_manager=token_manager; self.audit_log=audit_log

    def extract_bearer_token(self, headers) -> str | None:
        auth = headers.get("authorization") or headers.get("Authorization") or ""
        return auth[7:] if auth.startswith("Bearer ") else None

    def is_request_allowed(self, path: str, method: str = "GET", token: str | None = None) -> dict:
        cfg=self.config_service.get_default_config()
        if self.config_service.is_public_path(path): return {"allowed": True, "public": True}
        if cfg.mode == "compatibility" or not cfg.protectedEndpointsEnabled: return {"allowed": True, "compatibility": True}
        if not token:
            if self.audit_log: self.audit_log.add_entry("protected_request_blocked", summary=f"Protected request blocked: {path}", details={"reason":"missing_token"})
            return {"allowed": False, "reason":"Authentication required. Unlock Lumi first."}
        result=self.token_manager.verify_token(token)
        if not result:
            if self.audit_log: self.audit_log.add_entry("protected_request_blocked", summary=f"Protected request blocked: {path}", details={"reason":"invalid_or_expired_token"})
            return {"allowed": False, "reason":"Invalid or expired token."}
        if self.audit_log: self.audit_log.add_entry("protected_request_allowed", summary=f"Protected request allowed: {path}", details={"sessionId":result.get("sessionId")})
        return {"allowed": True, "sessionId": result.get("sessionId")}
