from typing import List, Optional
from lumi.app.schemas.security import SecretRecord, SecretValueEnvelope
from lumi.app.providers.redaction import RedactionUtil

class VaultStorage:
    def __init__(self, storage_adapter=None, audit_log=None, redaction: RedactionUtil | None = None):
        self.storage_adapter = storage_adapter
        self.audit_log = audit_log
        self.redaction = redaction or RedactionUtil()
        self._records: dict[str, SecretRecord] = {}
        self._values: dict[str, SecretValueEnvelope] = {}

    def save_secret_record(self, record: SecretRecord):
        self._records[record.secretId] = record
        if self.storage_adapter:
            try: self.storage_adapter.save_record("default", "vault_secrets_metadata", record.secretId, record.model_dump())
            except Exception: pass

    def save_secret_value(self, secret_id: str, envelope: SecretValueEnvelope):
        self._values[secret_id] = envelope
        if self.storage_adapter:
            try: self.storage_adapter.save_record("default", "vault_values", secret_id, envelope.model_dump())
            except Exception: pass

    def load_secret_records(self) -> List[SecretRecord]:
        if self.storage_adapter:
            try:
                for data in self.storage_adapter.load_collection("default", "vault_secrets_metadata"):
                    rec = SecretRecord(**data); self._records[rec.secretId] = rec
            except Exception: pass
        return list(self._records.values())

    def load_secret_value(self, secret_id: str) -> Optional[SecretValueEnvelope]:
        if secret_id in self._values: return self._values[secret_id]
        if self.storage_adapter:
            try:
                for data in self.storage_adapter.load_collection("default", "vault_values"):
                    if data.get("secretId") == secret_id:
                        env = SecretValueEnvelope(**data); self._values[secret_id] = env; return env
            except Exception: pass
        return None

    def delete_secret(self, secret_id: str):
        self._records.pop(secret_id, None); self._values.pop(secret_id, None)
        if self.storage_adapter:
            try:
                self.storage_adapter.delete_record("default", "vault_secrets_metadata", secret_id)
                self.storage_adapter.delete_record("default", "vault_values", secret_id)
            except Exception: pass

    def health(self) -> dict:
        return {"recordsCount": len(self._records), "valuesCount": len(self._values), "persistenceEnabled": self.storage_adapter is not None}
