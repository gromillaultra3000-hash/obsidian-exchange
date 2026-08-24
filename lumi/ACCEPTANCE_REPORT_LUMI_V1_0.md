# Acceptance Report — Lumi v1.0.0

Archive: `LUMI_V1_0_CONTROLLED_SANDBOX_TEST_APPLY_PREPARATION_FOUNDATION.zip`

Base: `LUMI_V0_9_PATCH_PLANNER_DIFF_PREVIEW_TEST_ROLLBACK_FOUNDATION.zip`

## Added in v1.0.0

- Sandbox workspace foundation from host project snapshots.
- Sandbox store and lifecycle operations.
- Synthetic diff preview application to in-memory sandbox representation.
- Command execution guard with strict allowlist and fail-closed blocklist.
- Preview-only sandbox test runner.
- Controlled sandbox mode safely blocked as not available unless future safe executor is implemented.
- Sandbox result store.
- Approval-gated apply preparation package.
- Apply package service with safe review payload.
- REST API router `/sandbox/*`.
- Dialog support for sandbox workspace, sandbox test, sandbox diff application, apply package preparation and review.
- Integration event support for sandbox workspace/test/apply preparation requests.

## Safety verification

- No host file writes.
- No host patch apply.
- No git operations.
- No network commands.
- No install commands.
- No unrestricted shell commands.
- No local filesystem scanning beyond existing snapshots.
- `canAffectHost` remains false.
- `canApplyToHost` remains false.
- Dangerous commands are blocked by CommandExecutionGuard.
- Preview-only test mode does not execute commands.
- Controlled sandbox mode returns blocked/not available.
- Secret-like command/output/package metadata is redacted.

## Checks

```bash
python -m compileall -q .
pytest -q
```

Result: `171 passed`.

JavaScript SDK/example syntax check also passed with `node --check`.

## Known limitations

- In-memory storage only.
- No persistent sandbox workspaces.
- No real host apply.
- No real rollback execution.
- No real external provider calls.
- No visual UI.
- Controlled sandbox execution is blocked/not available in this foundation layer.
