# Routing Runtime

The routing runtime creates a deterministic route plan before provider invocation.

## Flow

```text
TaskRequest -> TaskClassification -> TaskRequirements -> RoutePlan -> Resolve -> StructuredDecision
```

## Route statuses

- `READY`: required provider route is available.
- `PARTIAL`: a partial match exists, but requirements are incomplete.
- `FALLBACK`: fallback provider is used.
- `NO_ROUTE`: no enabled suitable provider exists.
- `BLOCKED`: routing is blocked by missing critical requirements.

## Route strategies

- `single_provider`
- `multi_provider_parallel`
- `fallback_only`
- `no_route`

## Endpoints

```bash
curl -X POST http://localhost:8000/routing/classify -H "Content-Type: application/json" -d @examples/resolve_code_review_task.json
curl -X POST http://localhost:8000/routing/requirements -H "Content-Type: application/json" -d @examples/resolve_code_review_task.json
curl -X POST http://localhost:8000/routing/plan -H "Content-Type: application/json" -d @examples/resolve_code_review_task.json
```
