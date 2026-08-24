from lumi.app.schemas.security import SecurityConfig, SecurityMode

PUBLIC_PATHS = [
    "/health", "/version", "/ui", "/ui/", "/dashboard", "/dashboard/state",
    "/ui/app.js", "/ui/styles.css", "/ui/components/", "/ui/static/",
    "/security/status", "/security/setup", "/security/unlock",
    "/favicon.ico", "/docs", "/openapi.json",
]

class SecurityConfigService:
    def __init__(self):
        self._config = SecurityConfig()

    def get_default_config(self) -> SecurityConfig:
        return self._config

    def set_mode(self, mode: SecurityMode):
        self._config.mode = mode
        self._config.protectedEndpointsEnabled = mode in ["protected", "locked"]
        return self._config

    def enable_protected_mode(self):
        return self.set_mode("protected")

    def disable_protected_mode(self):
        return self.set_mode("compatibility")

    def require_ui_unlock(self, enabled: bool):
        self._config.requireUnlockForUi = enabled
        return self._config

    def is_public_path(self, path: str) -> bool:
        return any(path == p or path.startswith(p) for p in PUBLIC_PATHS)

    def is_protected_path(self, path: str) -> bool:
        return not self.is_public_path(path)
