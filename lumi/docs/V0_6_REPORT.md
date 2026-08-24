# Lumi v0.6 — Development Report

## Implemented

- Decision history store with redacted metadata.
- Decision lookup, query, and filtering.
- Timeline builder from audit events.
- Human/technical/compact/dialog explanation layer.
- Dialog session store.
- Dialog message store with secret redaction.
- Deterministic command parser.
- Dialog runtime that converts natural-language input into `TaskRequest` and returns `DialogResponse`.
- Session-decision linking.
- Dialog response summaries for routing, validation, conflict, policy/action, and approval prompts.
- New API routers: history, explainability, dialog.

## Checks

```bash
python -m compileall -q .
pytest -q
```

Expected: all tests pass.

## Not implemented in v0.6

- Full frontend UI.
- Desktop/mobile dialog window.
- Real external provider API calls.
- Real host action execution.
- Persistent database.
- Authentication.
- Project scanner / patch generator.

## Safety

- Dialog does not execute actions.
- Dialog does not bypass Policy Engine.
- History, explanation, timeline, messages, and audit remain redacted.
