class DiffValidator:
    def __init__(self, config_service):
        self.config_service = config_service

    def validate(self, changes, config=None) -> dict:
        config = config or self.config_service.get_config()
        errors = []
        if not changes:
            errors.append("No changes provided")
        if len(changes) > config.maxFilesPerApply:
            errors.append(f"Too many files ({len(changes)} > {config.maxFilesPerApply})")
        total = 0
        for c in changes:
            content = c.afterContent if c.afterContent is not None else c.beforeContent or ""
            total += c.sizeBytes or len(str(content).encode("utf-8", errors="ignore"))
            if c.operation not in ("create", "update", "delete", "rename"):
                errors.append(f"Unsupported operation: {c.operation}")
        if total > config.maxTotalChangedBytes:
            errors.append(f"Total change size exceeds limit ({config.maxTotalChangedBytes})")
        return {"valid": not errors, "errors": errors, "totalBytes": total}
