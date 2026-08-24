# Dialog Session Foundation

v0.6 adds backend contracts for a future conversational control panel. It does not include a visual UI yet.

## Endpoints

```bash
POST /dialog/sessions
GET /dialog/sessions
GET /dialog/sessions/{sessionId}
POST /dialog/sessions/{sessionId}/close
POST /dialog/sessions/{sessionId}/message
GET /dialog/sessions/{sessionId}/messages
```

A normal dialog message is transformed into a `TaskRequest`, passed through the existing Lumi pipeline, linked to decision history, explained, and returned as a structured `DialogResponse`.

Dialog does not bypass policy, does not execute actions, and does not expose secrets.
