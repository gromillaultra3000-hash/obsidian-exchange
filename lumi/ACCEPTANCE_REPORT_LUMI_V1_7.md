# Acceptance Report — Lumi v1.7.0

Archive: LUMI_V1_7_CONTROLLED_REAL_APPLY_BACKUP_ROLLBACK_GATE_FOUNDATION.zip

Base: LUMI_V1_6_ADVANCED_PROVIDER_RUNTIME_MULTI_PROVIDER_RELIABILITY_FOUNDATION.zip

Checks:

- python -m compileall -q . — passed
- pytest -q — 203 passed
- node --check lumi/app/static/app.js — passed

Confirmed:

- Controlled apply disabled by default.
- Registered workspace required.
- Workspace allowApply default false.
- Path traversal blocked.
- Secret files/content blocked.
- Binary content blocked.
- Delete/rename blocked by default.
- Approval metadata required.
- Sandbox/test metadata required.
- Backup created before apply.
- Rollback package created.
- Rollback preview and rollback work.
- No shell/git/network apply execution.
- No background apply.
- Old runtime remains compatible.
