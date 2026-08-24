# Lumi v0.7 — SDK, REST Integration Layer & Local Sidecar Foundation

## Implemented
- Host app registry and manifest validation.
- Integration handshake endpoint and service.
- Stable REST connector contract.
- Host event processor for user_message, error_log, action_requested, approval_response and custom events.
- Decision callback contract with mock delivery and HTTP delivery blocked in v0.7.
- Local sidecar status and instructions contract.
- Python SDK client using standard library HTTP.
- JavaScript SDK client using fetch.
- Integration examples and docs.

## Safety
- No real host action execution.
- No real outbound HTTP callbacks.
- Unknown or disabled hosts reject events.
- Action events go through Action Gateway.
- Approval events only record approval decisions.
- Secret-like values are redacted from manifest, events, callback metadata and audit.

## Checks
Run:

```bash
python -m compileall -q .
pytest -q
```
