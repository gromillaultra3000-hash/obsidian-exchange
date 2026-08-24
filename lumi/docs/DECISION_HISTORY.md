# Decision History

Lumi v0.6 stores a compact redacted record for every structured decision returned by `/resolve`.

## Endpoints

```bash
GET /history/decisions
GET /history/decisions/{decisionId}
POST /history/decisions/query
GET /history/decisions/{decisionId}/timeline
```

## Query example

```json
{
  "status": "WAIT",
  "limit": 20,
  "offset": 0
}
```

The history record stores summary fields, not unsafe raw data. Metadata is redacted before storage.
