# Lumi v0.5 Policy Engine

Lumi v0.5 adds a fail-closed policy layer for host-application actions.

Default behavior:
- unknown actions are blocked;
- disabled actions are blocked;
- secret-like action input is blocked;
- high and critical risk actions require approval;
- execute mode never performs real side effects in v0.5;
- dry-run is allowed only if the action supports dry-run;
- SAFE_DEFAULT and REJECT decisions block actions;
- WAIT blocks dry-run/execute but can still allow a proposal.

Useful endpoints:

```bash
curl http://localhost:8000/policy/summary
curl http://localhost:8000/policy/rules
curl http://localhost:8000/policy/limits
```

Policy check:

```bash
curl -X POST http://localhost:8000/policy/check \
  -H "Content-Type: application/json" \
  -d '{"actionId":"delete_file","riskLevel":"critical","requestedMode":"execute"}'
```
