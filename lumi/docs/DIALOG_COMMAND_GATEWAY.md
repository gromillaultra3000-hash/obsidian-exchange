# Dialog Command Gateway

The dialog command parser is deterministic and does not call external APIs.

Supported command classes:

- `resolve_task`
- `explain_decision`
- `show_history`
- `show_status`
- `register_provider_help`
- `register_action_help`
- `approval_response`
- `unknown`

Unknown or closed sessions fail safely. Approval responses record approval decisions only; they do not execute host actions.
