# Lumi v0.5 Action Gateway

The Action Gateway is the single controlled entry point for host actions.

Flow:

```text
ActionDefinition -> ActionProposal -> PolicyCheck -> ApprovalPrompt/DryRunReady/Blocked
```

v0.5 does not execute real host actions. It only creates action proposals, policy checks, approval prompt contracts, and dry-run-ready contracts.

Register an action:

```bash
curl -X POST http://localhost:8000/actions/register \
  -H "Content-Type: application/json" \
  -d @examples/action_register_create_patch_preview.json
```

Propose an action:

```bash
curl -X POST http://localhost:8000/actions/propose \
  -H "Content-Type: application/json" \
  -d @examples/action_propose_patch_preview.json
```
