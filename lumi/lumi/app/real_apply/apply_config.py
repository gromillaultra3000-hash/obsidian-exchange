from lumi.app.schemas.real_apply import RealApplyConfig, ApplyMode

class RealApplyConfigService:
    def __init__(self, audit_log=None):
        self._config = RealApplyConfig()
        self.audit_log = audit_log

    def get_config(self) -> RealApplyConfig:
        return self._config

    def set_mode(self, mode: ApplyMode) -> RealApplyConfig:
        self._config.mode = mode
        if self.audit_log:
            self.audit_log.add_entry("real_apply_config_changed", summary=f"Real apply mode set to {mode}", details={"mode": mode})
        return self._config

    def enable_controlled_mode(self) -> RealApplyConfig:
        return self.set_mode("controlled")

    def disable_apply(self) -> RealApplyConfig:
        return self.set_mode("disabled")

    def validate_config(self, config: RealApplyConfig) -> dict:
        errors = []
        if config.maxFilesPerApply < 1:
            errors.append("maxFilesPerApply must be positive")
        if config.maxFileSizeBytes < 1:
            errors.append("maxFileSizeBytes must be positive")
        if config.maxTotalChangedBytes < 1:
            errors.append("maxTotalChangedBytes must be positive")
        return {"valid": not errors, "errors": errors}
