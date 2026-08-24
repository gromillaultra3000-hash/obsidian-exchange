# Controlled Test Execution

v1.0 supports preview-only sandbox test validation. Commands are validated by the command guard. Actual command execution in `controlled_sandbox` mode is blocked/not available unless a future fully isolated executor is added.

Allowed examples include `pytest -q`, `python -m compileall -q .`, `npm test`, `npm run build`, and `echo sandbox-check`.
