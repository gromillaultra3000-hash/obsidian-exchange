# Persistence & Local Storage

Lumi v1.2 adds local SQLite persistence and redacted JSON export/import for runtime state.

Default data path: `data/lumi_profiles/default/lumi_state.sqlite`.

Endpoints:
- `GET /persistence/status`
- `GET /persistence/health`
- `GET /persistence/profiles`
- `POST /persistence/save`
- `POST /persistence/load`
- `POST /persistence/export`
- `POST /persistence/import`

All persisted payloads are redacted. Raw API keys, tokens, passwords, and secret-like content must not be stored.
