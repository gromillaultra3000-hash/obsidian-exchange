# Lumi v0.4 — Conflict Detection & Deterministic Resolver

## Implemented

- Conflict schemas: ProviderDecisionSignal, ConflictFinding, ConflictAnalysisReport, DeterministicResolution.
- Conflict detector for ACTION_CONFLICT, RISK_CONFLICT, STRATEGY_CONFLICT, DATA_CONFLICT, CONFIDENCE_CONFLICT, VALIDATION_CONFLICT.
- Disagreement score based on conflict severity and confidence spread.
- Deterministic resolver with fail-closed priority rules.
- Integration into `/resolve` after routing and validation.
- New API endpoints:
  - `POST /conflict/analyze`
  - `POST /conflict/resolve`
- New audit events:
  - `conflict_analysis_completed`
  - `conflict_detected`
  - `deterministic_resolution_completed`
- Decision metadata now includes:
  - `conflictReport`
  - `deterministicResolution`
- Donor committee ideas were adapted in neutral form only. No domain-specific donor code was copied directly.

## Safety / fail-closed behavior

- no accepted outputs => SAFE_DEFAULT;
- no valid success outputs => SAFE_DEFAULT;
- risk/policy conflict => WAIT;
- approve/reject conflict => ASK_USER;
- data/confidence/validation conflict => WAIT;
- fallback route cannot approve;
- only high-confidence validated non-conflicting outputs can APPROVE.

## Verification

```bash
python -m compileall -q .
pytest -q
```

Expected result for accepted archive: all tests pass.

## Not implemented in v0.4

- real external provider API calls;
- policy engine;
- action gateway;
- project scanner;
- patch generator;
- persistent database;
- UI/dashboard;
- authentication;
- cloud mode.
