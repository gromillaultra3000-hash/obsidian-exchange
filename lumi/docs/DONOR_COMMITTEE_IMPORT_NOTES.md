# Donor Committee Import Notes — Lumi v0.4

A donor archive was inspected for reusable committee/runtime ideas. The original domain-specific implementation was not copied as-is. The following neutral, domain-agnostic patterns were extracted and adapted:

- multi-reviewer disagreement scoring;
- formal consensus/disagreement reporting;
- final outcome never depends on a single provider output;
- conservative handling of risk or policy disagreement;
- advisory/preview-only guard philosophy translated into neutral `actionAllowed=false` and fail-closed resolution;
- human-readable explanation metadata for why a resolution status was selected;
- audit events for conflict detection and deterministic resolution.

No domain-specific source names, trading logic, action submission logic, external write logic, or raw credentials handling were imported.
