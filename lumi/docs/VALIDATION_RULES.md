# Validation Rules

v0.3 validates provider outputs with deterministic rules:

- schema validity
- non-empty answer for success
- confidence range
- allowed suggested statuses
- evidence required for high-confidence approval
- errors required for error/timeout/invalid statuses
- unsafe execution wording detection
- secret-like content detection
- no fake success

Validation statuses:

- `valid`: output is strong enough to use normally
- `degraded`: output can be used cautiously
- `rejected`: output must not influence approval logic
