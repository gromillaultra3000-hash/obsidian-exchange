from __future__ import annotations
import os
import re
from lumi.app.schemas.real_apply import FileClassification

SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----", re.I),
    re.compile(r"api[_-]?key\s*=\s*[^\s]+", re.I),
    re.compile(r"secret\s*=\s*[^\s]+", re.I),
    re.compile(r"password\s*=\s*[^\s]+", re.I),
    re.compile(r"token\s*=\s*[^\s]+", re.I),
    re.compile(r"Authorization:\s*Bearer\s+[^\s]+", re.I),
    re.compile(r"x-api-key\s*[:=]\s*[^\s]+", re.I),
    re.compile(r"sk-test-secret", re.I),
]
SECRET_PATH_FRAGMENTS = [".env", "secret", "secrets", "credential", "credentials", "private", "id_rsa", "id_dsa", "keys/"]

class FileClassifier:
    def __init__(self, config_service, audit_log=None):
        self.config_service = config_service
        self.audit_log = audit_log

    def _content(self, change) -> str:
        return change.afterContent if change.afterContent is not None else change.beforeContent or ""

    def detect_binary_content(self, content: str) -> bool:
        if content is None:
            return False
        if "\x00" in content:
            return True
        try:
            content.encode("utf-8").decode("utf-8")
            return False
        except Exception:
            return True

    def detect_secret_like_path(self, path: str) -> bool:
        low = (path or "").replace('\\','/').lower()
        return any(f in low for f in SECRET_PATH_FRAGMENTS)

    def detect_secret_like_content(self, content: str) -> bool:
        return any(p.search(content or "") for p in SECRET_PATTERNS)

    def classify_change(self, change, config=None) -> FileClassification:
        config = config or self.config_service.get_config()
        path = change.path
        op = change.operation or "unknown"
        blockers, warnings = [], []
        ext = os.path.splitext(path.lower())[1]
        content = self._content(change)
        size = len((content or "").encode("utf-8", errors="ignore"))
        if op == "delete" and not config.allowDelete:
            blockers.append("Delete operation blocked by default")
        if op == "rename" and not config.allowRename:
            blockers.append("Rename operation blocked by default")
        if op == "create" and not config.allowCreate:
            blockers.append("Create operation disabled")
        if op == "update" and not config.allowUpdate:
            blockers.append("Update operation disabled")
        if op not in ("create", "update", "delete", "rename"):
            blockers.append(f"Unsupported operation: {op}")
        if ext in {e.lower() for e in config.blockedExtensions}:
            blockers.append(f"Blocked extension: {ext}")
        if ext and config.allowedExtensions and ext not in {e.lower() for e in config.allowedExtensions}:
            blockers.append(f"Extension not allowed: {ext}")
        is_secret_path = self.detect_secret_like_path(path)
        is_secret_content = self.detect_secret_like_content(content)
        if is_secret_path:
            blockers.append("Secret-like path blocked")
        if is_secret_content:
            blockers.append("Secret-like content blocked")
        is_binary = self.detect_binary_content(content)
        if is_binary:
            blockers.append("Binary content blocked")
        if size > config.maxFileSizeBytes:
            blockers.append(f"File exceeds max size ({config.maxFileSizeBytes})")
        allowed = not blockers
        if self.audit_log:
            self.audit_log.add_entry("file_classified" if allowed else "file_classification_blocked", summary=f"File {'allowed' if allowed else 'blocked'}: {path}", details={"path": path, "operation": op, "blockers": blockers})
        return FileClassification(path=path, operation=op, isText=not is_binary, isBinary=is_binary, isSecretLike=is_secret_path or is_secret_content, extension=ext, sizeBytes=size, allowed=allowed, blockers=blockers, warnings=warnings)
