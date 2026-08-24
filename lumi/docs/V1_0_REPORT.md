# Lumi v1.0.0 — Controlled Sandbox Test Execution & Apply Preparation Foundation

## Implemented

- Sandbox workspace creation from host project snapshots.
- In-memory sandbox store and discard lifecycle.
- Synthetic diff preview application to sandbox representation only.
- Command execution guard with strict allowlist and blocklist.
- Preview-only sandbox test runner. `controlled_sandbox` is safely blocked as not available unless a future fully isolated executor is implemented.
- Sandbox test result store.
- Approval-gated apply preparation package.
- Apply package review payload.
- REST API router `/sandbox/*`.
- Dialog command support for sandbox workspace, sandbox tests, diff preview application, apply preparation, and apply package review.
- Integration events for sandbox workspace, sandbox test, and apply preparation requests.

## Safety guarantees in v1.0.0

- No host project writes.
- No real patch apply to host project.
- No git operations.
- No network commands.
- No package install commands.
- No unrestricted shell execution.
- `canAffectHost` remains `false`.
- `canApplyToHost` remains `false`.
- Command guard blocks shell operators, destructive commands, network commands, install commands, path traversal, and unknown commands.

## Known limitations

- In-memory storage only.
- No persistent sandbox workspaces.
- No real host apply.
- No real rollback execution.
- Controlled sandbox execution is blocked/not available in this foundation layer.
