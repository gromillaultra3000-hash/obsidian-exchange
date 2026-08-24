# Acceptance Report — Lumi v0.2

Archive: `LUMI_V0_2_CAPABILITY_ROLE_ROUTING_RUNTIME.zip`
Base: `LUMI_V0_1_CORE_RUNTIME_PROVIDER_FOUNDATION.zip`

## Accepted scope

Lumi v0.2 extends the accepted v0.1 foundation with a routing layer based on provider capabilities and roles.

Implemented and verified:

- Version metadata updated to `0.2.0` / `CAPABILITY_ROLE_ROUTING_RUNTIME`.
- Capability catalog with 20 capabilities.
- Capability profile normalization, unknown capability detection, matching, and scoring.
- Role catalog with 15 roles.
- Role suggestion endpoint.
- Role-fit endpoint.
- Deterministic task classifier.
- Task requirements builder.
- Route plan model and provider router.
- Routing resolver integrated into `/resolve`.
- Fallback routing support.
- Multi-provider mock routing support.
- Routing metadata inside `StructuredDecision.metadata`.
- Routing audit events:
  - `task_classified`
  - `task_requirements_built`
  - `route_plan_created`
  - `provider_selected`
  - `routing_failed`
  - `fallback_route_used`
  - `roles_suggested`
  - `role_fit_checked`
- New API endpoints:
  - `GET /capabilities`
  - `GET /roles`
  - `POST /routing/classify`
  - `POST /routing/requirements`
  - `POST /routing/plan`
  - `POST /providers/{providerId}/suggest-roles`
  - `GET /providers/{providerId}/role-fit`
- Expanded mock-provider scenarios:
  - `code_review_success`
  - `risk_review_wait`
  - `validator_approve`
  - `critic_reject`
  - `fallback_success`
  - v0.1 scenarios preserved.
- Backward-compatible v0.1 generic mock `/resolve` smoke behavior preserved.
- Secret redaction preserved and extended to routing metadata/audit/provider APIs.
- Strict `__init__.py` package checks preserved and expanded.
- No `init.py` files.
- No external API calls.

## Corrections applied during acceptance

The developer's supplied v0.2 text was not directly acceptable as-is. Corrections made:

- Integrated changes into the real accepted v0.1 archive instead of using a separate inconsistent tree.
- Kept the actual FastAPI entrypoint as `lumi/app/main.py`; ignored the incorrect `lumi/app/api/main.py` direction.
- Preserved v0.1 redaction, structured error envelopes, `reset_for_tests`, and idempotent runtime initialization.
- Reworked routing so v0.1 generic mock providers still support old smoke tests.
- Added missing strict schema files for capabilities, roles, and routing.
- Added stronger route plan behavior and metadata.
- Added real acceptance tests beyond the developer's partial report.
- Updated tests for v0.2 version metadata.
- Added missing docs and examples.

## Verification commands

```bash
python -m compileall -q .
pytest -q
```

## Verification result

```text
63 passed
```

## Known limitations for v0.2

- Mock providers only.
- In-memory registry and audit only.
- No real external provider API calls.
- No full conflict resolver yet.
- No policy engine yet.
- No action gateway yet.
- No project scanner / patch planner yet.
- No persistent database.
- No UI/dashboard.
- No authentication or cloud mode.

## Acceptance status

Accepted as a working v0.2 routing foundation.
