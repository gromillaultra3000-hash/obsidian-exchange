class SecurityAuditHelper:
    SECURITY_PREFIXES = ("security_", "secret_", "vault_", "encryption_", "protected_")
    def __init__(self, audit_log=None): self.audit_log = audit_log
    def summary(self):
        entries = self.audit_log.list_entries() if self.audit_log else []
        filtered = [e for e in entries if e.eventType.startswith(self.SECURITY_PREFIXES)]
        return {"totalSecurityEvents": len(filtered), "recentEvents": [e.model_dump() for e in filtered[-20:]]}
