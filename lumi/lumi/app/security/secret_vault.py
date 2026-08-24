import uuid
from datetime import datetime, timezone
from typing import Optional
from lumi.app.schemas.security import SecretCreateRequest, SecretUpdateRequest, SecretRecord, SecretValueEnvelope, SecretListResult, SecretResolveResult
from lumi.app.providers.redaction import RedactionUtil

class SecretVault:
    def __init__(self, vault_storage, encryption_service, audit_log=None, redaction: RedactionUtil | None = None):
        self.vault_storage=vault_storage; self.encryption_service=encryption_service; self.audit_log=audit_log; self.redaction=redaction or RedactionUtil()

    def _mask_value(self, value: str) -> str:
        if not value or len(value) <= 6: return "****"
        return value[:3] + "..." + value[-4:]

    def create_secret(self, request: SecretCreateRequest) -> SecretRecord:
        if not self.encryption_service.is_configured(): raise RuntimeError("Encryption not configured. Setup and unlock security first.")
        sid=str(uuid.uuid4()); now=datetime.now(timezone.utc).isoformat(); enc=self.encryption_service.encrypt_string(request.value)
        env=SecretValueEnvelope(secretId=sid, encryptedValue=enc["encryptedValue"], algorithm=enc["algorithm"], createdAt=now)
        self.vault_storage.save_secret_value(sid, env)
        rec=SecretRecord(secretId=sid, name=request.name, kind=request.kind, status="active", providerId=request.providerId, secretRef=f"vault://secret/{sid}", maskedValue=self._mask_value(request.value), createdAt=now, updatedAt=now, labels=request.labels, metadata=self.redaction.redact_dict(request.metadata or {}))
        self.vault_storage.save_secret_record(rec)
        if self.audit_log: self.audit_log.add_entry("secret_created", summary=f"Secret created: {request.name}", details={"secretId":sid,"kind":request.kind})
        return rec

    def list_secrets(self) -> SecretListResult:
        records=self.vault_storage.load_secret_records(); return SecretListResult(secrets=records, count=len(records), redacted=True)

    def get_secret(self, secret_id: str) -> Optional[SecretRecord]:
        return next((r for r in self.vault_storage.load_secret_records() if r.secretId == secret_id), None)

    def update_secret(self, secret_id: str, request: SecretUpdateRequest) -> Optional[SecretRecord]:
        rec=self.get_secret(secret_id)
        if not rec: return None
        now=datetime.now(timezone.utc).isoformat()
        if request.value is not None:
            enc=self.encryption_service.encrypt_string(request.value)
            self.vault_storage.save_secret_value(secret_id, SecretValueEnvelope(secretId=secret_id, encryptedValue=enc["encryptedValue"], algorithm=enc["algorithm"], createdAt=now))
            rec.maskedValue=self._mask_value(request.value)
        if request.status is not None: rec.status=request.status
        if request.labels is not None: rec.labels=request.labels
        rec.updatedAt=now; self.vault_storage.save_secret_record(rec)
        if self.audit_log: self.audit_log.add_entry("secret_updated", summary=f"Secret updated: {secret_id}")
        return rec

    def delete_secret(self, secret_id: str) -> Optional[SecretRecord]:
        rec=self.get_secret(secret_id)
        if not rec: return None
        rec.status="deleted"; rec.updatedAt=datetime.now(timezone.utc).isoformat(); self.vault_storage.save_secret_record(rec); self.vault_storage.delete_secret(secret_id)
        if self.audit_log: self.audit_log.add_entry("secret_deleted", summary=f"Secret deleted: {secret_id}")
        return rec

    def resolve_secret(self, secret_ref: str, purpose: str = "") -> SecretResolveResult:
        if not secret_ref.startswith("vault://secret/"):
            return SecretResolveResult(resolved=False, secretRef=secret_ref, warnings=["Invalid secret reference format"])
        sid=secret_ref.split("vault://secret/",1)[1]; rec=self.get_secret(sid)
        if not rec or rec.status != "active":
            if self.audit_log: self.audit_log.add_entry("secret_resolve_failed", summary="Secret resolve failed", details={"secretId": sid})
            return SecretResolveResult(resolved=False, secretRef=secret_ref, warnings=["Secret not found or inactive"])
        if self.audit_log: self.audit_log.add_entry("secret_resolved", summary="Secret reference resolved", details={"secretId":sid,"purpose":purpose})
        return SecretResolveResult(resolved=True, secretRef=secret_ref, secretId=sid, valueAvailable=True, maskedValue=rec.maskedValue)

    def internal_get_secret_value(self, secret_ref: str) -> Optional[str]:
        if not secret_ref.startswith("vault://secret/"): return None
        sid=secret_ref.split("vault://secret/",1)[1]; env=self.vault_storage.load_secret_value(sid)
        if not env: return None
        try: return self.encryption_service.decrypt_string(env.model_dump())
        except Exception: return None
