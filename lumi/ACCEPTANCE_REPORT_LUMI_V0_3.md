# ACCEPTANCE REPORT — Lumi v0.3

Archive: `LUMI_V0_3_NORMALIZED_OUTPUT_VALIDATION_PIPELINE.zip`
Base: accepted `LUMI_V0_2_CAPABILITY_ROLE_ROUTING_RUNTIME.zip`

## Status

Accepted as working validation foundation.

## Implemented

- Version metadata updated to `0.3.0` / `NORMALIZED_OUTPUT_VALIDATION_PIPELINE`.
- Added `lumi/app/validation` package.
- Added validation schemas: `ValidationIssue`, `ProviderOutputValidationResult`, `NormalizedOutputEnvelope`, `ValidationPipelineResult`.
- Added `OutputNormalizer` for `ProviderOutput`, dict, plain string and `None`.
- Added deterministic validation rules.
- Added unsafe wording detector for English and Russian forbidden execution claims.
- Added secret-like content detection and redaction.
- Added validation scoring.
- Added output validator.
- Added batch validation pipeline.
- Added `ValidatedRoutingResolver` integrated into `/resolve`.
- Added `/validation/normalize`, `/validation/validate-output`, `/validation/validate-batch`.
- Extended mock provider scenarios for validation tests.
- Added validation audit events.
- Preserved v0.1/v0.2 routes and behavior.

## Important acceptance corrections

- Kept the real entrypoint as `lumi/app/main.py`; did not accept the erroneous `lumi/app/api/main.py` entrypoint pattern.
- Preserved `reset_for_tests`, idempotent init, structured errors, redaction and routing foundations from v0.1/v0.2.
- Added secret-like redaction inside string values, not only sensitive keys.
- Ensured rejected outputs cannot influence approval logic.
- Ensured all-rejected validation results produce `SAFE_DEFAULT`.
- Ensured no raw secret-like values appear in validation metadata or audit.
- Added route-aware tests so validation is checked through real `/resolve` flow.

## Verification

```bash
python -m compileall -q .
pytest -q
```

Result:

```text
104 passed
```

## Known limitations

- Mock providers only.
- In-memory storage only.
- No real external provider calls.
- No full conflict resolver yet.
- No policy engine yet.
- No action gateway yet.
- No project scanner / patch generator yet.
- No persistent DB.
- No UI/dashboard/auth/cloud mode.

## Next layer

The next planned layer is Conflict Detection & Deterministic Resolver.
