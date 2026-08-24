# Lumi v1.7.0 — Controlled Real Apply, Backup & Rollback Gate Foundation

## Summary

v1.7 adds the first controlled real file-apply layer. It is disabled by default and can write only inside an explicitly registered safe workspace after the apply gate passes. The gate requires controlled mode, workspace allowApply, safe paths, text-only changes, sandbox/test evidence, approval metadata, and backup readiness.

## Added

- Real Apply configuration, disabled by default.
- Safe Workspace Registry.
- Path Guard with workspace-boundary enforcement.
- File Classifier for text/binary/secret-like checks.
- Diff Validator for change count and size limits.
- Apply Gate.
- Backup Service.
- Apply Executor with atomic text writes.
- Rollback Service and rollback preview.
- `/real-apply/*` API.
- UI Real Apply panel.
- RU/EN i18n keys.

## Safety

- No shell execution.
- No git execution.
- No network calls for apply.
- Delete and rename blocked by default.
- Secret-like files and content blocked.
- Binary files blocked.
- Backup content is not returned through APIs.
- Export/persistence stores safe metadata only.

## Checks

- `python -m compileall -q .`
- `pytest -q`
- `node --check lumi/app/static/app.js`
