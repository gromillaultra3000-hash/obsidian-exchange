# REST Contract

Base URL for local sidecar mode: `http://127.0.0.1:8000`.

Core endpoints:
- `GET /health`
- `GET /version`
- `GET /runtime/status`
- `POST /integration/handshake`
- `POST /integration/events`
- `POST /resolve`
- `POST /dialog/sessions`
- `POST /dialog/sessions/{id}/message`
- `POST /actions/register`
- `POST /actions/propose`
- `GET /actions/approvals`
- `POST /actions/approvals/{id}/decision`
- `GET /history/decisions`
- `GET /explain/{decisionId}`

Errors use `ErrorEnvelope`.
