# ADR-0031: Ed25519 review audit retention and deletion boundary

Status: structural contract frozen; external workspaces, deletion and physical erasure remain unimplemented.

The retention policy separates public contract material, hash-only audit
metadata, external sensitive review evidence, WebAuthn assertion bytes and
secrets/private keys. Audit metadata is limited to hash-only fields and
decisions; identity, credential content, assertion bytes, artifact contents,
paths and free text are forbidden. Secrets and private keys are rejected from
the review bundle, audit trail, repository and rehearsal workspace.

The deletion receipt is closed and binds the reviewed bundle, retention policy,
complete workspace inventory, deletion plan, caller nonce and a canonical
self-digest. A receipt ID and caller nonce are single-use; either replay blocks
consumption. `COMPLETE` requires every inventoried location attempted, zero
failures, zero ordinary backup copies and a distinct independent witness.
`PARTIAL`, `FAILED` or `UNKNOWN` cannot satisfy the audit privacy/retention
gate, and `physical_erasure_proven` remains permanently false because the
receipt proves procedure and scan evidence, not physical erasure.

This is a keyless symbolic boundary. It creates no external workspace, stores
no sensitive evidence, performs no deletion or scan, selects no backend and
grants no gate, crypto or runtime authority.

Evidence: `tests/test_e5_ed25519_audit_retention.py` and the closed fixtures
`ed25519-corpus-review-audit-retention-policy-v1.json` and
`ed25519-corpus-review-deletion-receipt-v1.schema.json`.
