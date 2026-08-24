from lumi.app.schemas.integration import HostAppManifest
from lumi.app.providers.redaction import RedactionUtil
from lumi.app.version.metadata import CAPABILITIES


class HostManifestValidator:
    def __init__(self, redaction: RedactionUtil | None = None):
        self.redaction = redaction or RedactionUtil()
        self.valid_app_types = {"desktop", "mobile", "web", "backend", "cli", "service", "unknown"}
        self.valid_connector_modes = {"rest", "sdk", "sidecar", "embedded", "webhook"}

    def validate_manifest(self, manifest: HostAppManifest) -> dict:
        errors: list[str] = []
        warnings: list[str] = []
        if not (manifest.hostAppId or "").strip():
            errors.append("hostAppId is required")
        if not (manifest.displayName or "").strip():
            errors.append("displayName is required")
        if manifest.appType not in self.valid_app_types:
            errors.append(f"invalid appType: {manifest.appType}")
        if not manifest.allowedModes:
            errors.append("at least one allowedMode is required")
        for mode in manifest.allowedModes:
            if mode not in self.valid_connector_modes:
                errors.append(f"invalid connector mode: {mode}")
        if not isinstance(manifest.actionsAllowed, list):
            errors.append("actionsAllowed must be a list")
        if not isinstance(manifest.eventsSupported, list):
            errors.append("eventsSupported must be a list")
        unknown_caps = [cap for cap in manifest.capabilitiesRequested if cap not in CAPABILITIES]
        if unknown_caps:
            warnings.append(f"unknown capabilities requested: {unknown_caps}")
        combined = f"{manifest.callbacks} {manifest.metadata}"
        redacted = self.redaction.redact_secret_like(combined)
        if redacted != combined:
            warnings.append("secret-like content detected and will be redacted")
        return {"valid": not errors, "errors": errors, "warnings": warnings}
