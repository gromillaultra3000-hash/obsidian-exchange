from lumi.app.schemas.project_scanner import ProjectManifest
from lumi.app.providers.redaction import RedactionUtil

class ProjectManifestValidator:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()
        self.valid_types = {"python", "javascript", "typescript", "mixed", "mobile", "web", "backend", "desktop", "unknown"}
        self.valid_modes = {"manifest_only", "snapshot", "static_inspection", "improvement_plan"}

    def validate_manifest(self, manifest: ProjectManifest) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        if not manifest.projectId or not manifest.projectId.strip():
            errors.append("projectId is required")
        if not manifest.displayName or not manifest.displayName.strip():
            errors.append("displayName is required")
        if manifest.projectType not in self.valid_types:
            warnings.append(f"Unknown projectType: {manifest.projectType}")
        if not manifest.allowedScanModes:
            errors.append("At least one allowedScanMode is required")
        for mode in manifest.allowedScanModes:
            if mode not in self.valid_modes:
                warnings.append(f"Unknown scan mode: {mode}")
        for name in ["declaredEntryPoints", "declaredTestPaths", "declaredConfigFiles", "declaredDocs"]:
            if not isinstance(getattr(manifest, name), list):
                errors.append(f"{name} must be a list")
        # Metadata may contain sensitive values; do not reject solely for it, warn and rely on redaction.
        if manifest.metadata and self.redaction.redact_dict(manifest.metadata) != manifest.metadata:
            warnings.append("metadata contains secret-like keys or values and will be redacted")
        return {"valid": not errors, "errors": errors, "warnings": warnings}
