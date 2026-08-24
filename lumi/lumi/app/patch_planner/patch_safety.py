from lumi.app.schemas.patch_planner import PatchRequest
from lumi.app.providers.redaction import RedactionUtil

class PatchSafetyGuard:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()
        self.forbidden_path_patterns = [".env", "id_rsa", "private_key", "secrets", "tokens", "credentials", ".pem", ".key", "secret"]
        self.forbidden_operations = ["delete_file", "shell", "exec", "subprocess", "git", "apply", "execute", "run_test", "rollback_execute", "run_tests", "apply_patch", "rollback_patch"]
        self.forbidden_path_traversal = ["../", "..\\"]

    def validate_patch_request(self, request: PatchRequest, project_profile=None, snapshots=None) -> dict:
        errors, warnings = [], []
        if not request.projectId:
            errors.append("Missing projectId")
        for file_path in request.targetFiles:
            fp = file_path or ""
            if any(traversal in fp for traversal in self.forbidden_path_traversal):
                errors.append(f"Path traversal detected in target file: {fp}")
            if fp.startswith("/") or fp.startswith("\\"):
                errors.append(f"Absolute path is not allowed in patch preview: {fp}")
            for pattern in self.forbidden_path_patterns:
                if pattern.lower() in fp.lower():
                    errors.append(f"Forbidden file path: {fp} (matches pattern: {pattern})")
                    break
        for change in request.requestedChanges:
            ct = str(change.get("changeType", "unknown")).lower()
            description = str(change.get("description", ""))
            combined = (ct + " " + description).lower()
            if ct in self.forbidden_operations or any(op in combined for op in ["subprocess", "shell", "os.system", "git ", "rm -rf", "pytest", "npm test"]):
                errors.append(f"Forbidden operation requested: {ct}")
            if ct == "delete_file":
                errors.append("Delete file operations are blocked in this version")
            if self._has_secret_like(description):
                warnings.append("Secret-like content detected and will be redacted")
        return {"valid": len(errors) == 0, "errors": sorted(set(errors)), "warnings": sorted(set(warnings)), "riskLevel": self.detect_risk(request)}

    def detect_risk(self, request: PatchRequest):
        if request.riskLevel and request.riskLevel != "unknown":
            return request.riskLevel
        for path in request.targetFiles:
            if any(p in path.lower() for p in self.forbidden_path_patterns):
                return "critical"
        change_types = {str(c.get("changeType", "unknown")) for c in request.requestedChanges}
        if change_types & {"delete_file", "rename_file", "move_file"}:
            return "critical"
        if change_types & {"security_fix"}:
            return "high"
        if change_types & {"refactor", "update_file", "config_change"}:
            return "medium"
        return "low"

    def check_forbidden_operations(self, request: PatchRequest):
        forbidden = []
        for change in request.requestedChanges:
            ct = str(change.get("changeType", "unknown")).lower()
            if ct in self.forbidden_operations:
                forbidden.append(ct)
        return forbidden

    def sanitize_patch_metadata(self, data: dict) -> dict:
        return self.redaction.redact_dict(data or {})

    def _has_secret_like(self, text: str) -> bool:
        lower = (text or "").lower()
        return any(p in lower for p in ["api_key", "apikey", "secret", "token", "password", "bearer", "authorization"])
