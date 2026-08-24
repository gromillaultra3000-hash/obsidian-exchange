# Explainability

Lumi v0.6 can build human-readable and technical explanations for stored decisions.

## Endpoints

```bash
GET /explain/{decisionId}?mode=human
GET /explain/{decisionId}?mode=technical&includeTimeline=true
POST /explain
```

## Modes

- `human`: short user-facing explanation.
- `technical`: structured detail for developers/operators.
- `compact`: short card-style explanation.
- `dialog`: response style for dialog runtime.

Explanations include status, confidence, route, validation, conflict, policy/action, next step, and optional timeline.
