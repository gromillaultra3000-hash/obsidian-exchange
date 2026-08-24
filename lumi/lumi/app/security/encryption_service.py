import base64, hashlib, hmac, secrets
from typing import Optional

class EncryptionService:
    def __init__(self, audit_log=None):
        self._master_key: Optional[bytes] = None
        self._configured = False
        self.algorithm = "hmac-xor-stdlib-fallback"
        self.audit_log = audit_log

    def configure_master_key_from_password(self, password: str, salt: str):
        self._master_key = hashlib.pbkdf2_hmac('sha256', password.encode(), salt.encode(), 200_000, dklen=32)
        self._configured = True
        if self.audit_log: self.audit_log.add_entry("encryption_configured", summary="Encryption key configured", details={"algorithm": self.algorithm})

    def is_configured(self) -> bool: return self._configured and self._master_key is not None

    def encrypt_string(self, value: str) -> dict:
        if not self.is_configured(): raise RuntimeError("Encryption not configured")
        nonce = secrets.token_bytes(16); pt = value.encode()
        stream = hashlib.pbkdf2_hmac('sha256', self._master_key, nonce, 1, dklen=len(pt))
        ct = bytes(a ^ b for a,b in zip(pt, stream)); mac = hmac.new(self._master_key, nonce+ct, hashlib.sha256).digest()
        return {"encryptedValue": base64.b64encode(nonce+ct+mac).decode(), "algorithm": self.algorithm}

    def decrypt_string(self, envelope: dict) -> str:
        if not self.is_configured(): raise RuntimeError("Encryption not configured")
        raw=base64.b64decode(envelope.get("encryptedValue", "")); nonce=raw[:16]; mac=raw[-32:]; ct=raw[16:-32]
        expected=hmac.new(self._master_key, nonce+ct, hashlib.sha256).digest()
        if not hmac.compare_digest(mac, expected): raise ValueError("Encrypted value authentication failed")
        stream=hashlib.pbkdf2_hmac('sha256', self._master_key, nonce, 1, dklen=len(ct))
        return bytes(a ^ b for a,b in zip(ct, stream)).decode()

    def clear_key(self):
        self._master_key=None; self._configured=False
