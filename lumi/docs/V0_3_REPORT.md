# Lumi v0.3 — Normalized Output & Validation Pipeline

## Implemented

- Output normalizer for ProviderOutput, dict, string and None
- Validation schemas
- Deterministic validation rules
- Unsafe wording detector in English and Russian
- Secret-like content detector
- Validation scorer
- Output validator
- Batch validation pipeline
- Validated routing resolver integrated into `/resolve`
- Validation API endpoints
- Validation audit events
- Extended mock provider scenarios

## Checks

Run:

```bash
python -m compileall -q .
pytest -q
```

## Not implemented

- full conflict resolver
- policy engine
- action gateway
- project scanner
- persistent DB
- UI/dashboard
- authentication/cloud mode
