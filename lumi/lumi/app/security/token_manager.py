import secrets, hashlib, uuid
from datetime import datetime, timezone, timedelta

class TokenManager:
    def __init__(self, audit_log=None):
        self._tokens: dict[str, dict] = {}
        self.audit_log = audit_log

    def _hash(self, token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()

    def create_token(self, session_id: str | None = None, ttl_minutes: int = 120) -> dict:
        raw = secrets.token_urlsafe(32); th = self._hash(raw)
        now = datetime.now(timezone.utc); exp = now + timedelta(minutes=ttl_minutes)
        rec = {"sessionId": session_id or str(uuid.uuid4()), "createdAt": now.isoformat(), "expiresAt": exp.isoformat()}
        self._tokens[th] = rec
        if self.audit_log: self.audit_log.add_entry("security_token_created", summary="Security token created", details={"sessionId": rec["sessionId"]})
        return {"accessToken": raw, "tokenType": "Bearer", "expiresAt": exp.isoformat(), "sessionId": rec["sessionId"]}

    def verify_token(self, token: str | None):
        if not token: return None
        rec = self._tokens.get(self._hash(token))
        if not rec: return None
        try: exp = datetime.fromisoformat(rec["expiresAt"])
        except Exception: return None
        if datetime.now(timezone.utc) > exp:
            self._tokens.pop(self._hash(token), None); return None
        return {"valid": True, "sessionId": rec["sessionId"]}

    def revoke_token(self, token: str):
        self._tokens.pop(self._hash(token), None)
        if self.audit_log: self.audit_log.add_entry("security_token_revoked", summary="Security token revoked")

    def revoke_all(self):
        count=len(self._tokens); self._tokens.clear()
        if self.audit_log: self.audit_log.add_entry("security_sessions_revoked", summary=f"All sessions revoked ({count})")

    def cleanup_expired(self):
        now=datetime.now(timezone.utc)
        for h,r in list(self._tokens.items()):
            if now > datetime.fromisoformat(r["expiresAt"]): self._tokens.pop(h, None)

    def list_active_sessions(self):
        self.cleanup_expired(); return list(self._tokens.values())
