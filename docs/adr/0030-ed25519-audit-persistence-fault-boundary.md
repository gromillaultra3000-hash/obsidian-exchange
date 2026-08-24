# ADR-0030: Ed25519 review audit persistence and fault boundary

Status: structural contract frozen; storage and external deletion remain unimplemented.

The review audit trail is append-only, hash-linked and minimized. A visible
internal state transition must commit its immutable audit event, audit head and
state row atomically. Compare-and-set checks the expected state, sequence and
previous event digest, so a restart cannot expose a state without its
authorizing event or an event without its state transition.

An external deletion attempt is represented by one immutable `PREPARED`
location intent before invocation. The intent may be invoked at most once. If
invocation may have begun and the durable outcome is absent, recovery produces
`UNKNOWN_REVIEW`; it never assumes success and never automatically invokes the
uncertain effect again. A committed terminal outcome is read, not repeated.

The ten-case fault matrix covers transaction staging, acknowledgement loss,
external-effect uncertainty, read-only scan failure and missing independent
checkpoints. A missing checkpoint leaves the local chain only locally
consistent and blocks the gate. This slice is symbolic/read-only: it selects no
backend, creates no store, performs no deletion, and grants no gate, crypto or
runtime authority.

Evidence: `tests/test_e5_ed25519_audit_persistence_faults.py` and the closed
fixtures `ed25519-corpus-review-audit-persistence-contract-v1.json` and
`ed25519-corpus-review-audit-fault-matrix-v1.json`.
