# E4 one-shot safety freeze

Status: **NO-GO / execution disabled**.

Do not run `e4_one_shot_termux.py`, `e4_owner_one_shot_server.py`,
`e4_owner_rehearsal_execute.py`, or the legacy `e4_memfd_handoff.py`. Do not
sign or reuse payloads v11, v12, or v13. They are expired; v12/v13 also contain
the superseded 30-minute window, and the legacy payloads do not bind the
current execution release.

The experimental path now fails closed before one-shot execution. The legacy
memfd handoff also fails closed because it transmitted decrypted private-key
bytes to a remote process. No private key may leave its controlling device.

The next canonical E4 item is one internal, non-executing design slice:
version and freeze a v2 plan/receipt contract that distinguishes retention of
the immutable encrypted source from mandatory destruction of the disposable
target and all transient plaintext. Until that contract, its tests and
independent review exist, no fresh owner/reviewer/root ceremony should start.

After that slice, the remaining ceremony must use separate file-based offline
owner and trust-root signing, a genuinely independent reviewer device, a
fresh pinned RFC3161 timestamp over the final bundle, a durable cross-run replay
authority, an independently frozen release allowlist, and an explicit
non-consuming preflight followed by a separate exact-digest execute consent.
