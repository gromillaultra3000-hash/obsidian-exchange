# Dialog Approval Contract

v0.5 prepares backend contracts for a future conversational control panel.

The visual dialog window is not implemented in v0.5. The backend now returns `ApprovalPrompt` objects that a UI can render.

ApprovalPrompt includes:
- promptId;
- title;
- message;
- riskLevel;
- buttons;
- defaultButton;
- requiresExplicitApproval;
- status.

Safety defaults:
- default button is `reject` or `close`;
- approval requires explicit user action;
- dialog/UI cannot bypass Policy Engine;
- execute mode does not perform real side effects in v0.5.

Record a decision:

```bash
curl -X POST http://localhost:8000/actions/approvals/{promptId}/decision \
  -H "Content-Type: application/json" \
  -d '{"promptId":"<promptId>","decision":"approve","userId":"operator"}'
```
