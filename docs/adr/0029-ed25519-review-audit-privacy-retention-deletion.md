# ADR 0029: Audit privacy, retention and deletion

Date: 2026-08-15

Status: policy and receipt contract frozen; no real storage or deletion

ADR 0028 gate `i09` requires auditability without turning the repository or
ordinary logs into a personnel and credential archive. This record separates
public contract material, minimized hash-only audit metadata, temporary external
sensitive evidence, short-lived WebAuthn assertion bytes and prohibited secrets.

Public ADR/schema/synthetic corpus material contains no real identities and may
remain while its contract version is supported. Hash-only audit records retain
closed event fields for seven 365-day years in an append-only dedicated store.
External sensitive review copies live at most 24 hours; verifier copies of
assertion bytes live at most ten minutes. Both remain outside the repository and
ordinary backups, encrypted and access-limited, and are deleted after decision
or expiry. Secrets/private keys are rejected and never copied for review.

Audit events permit only opaque domain IDs, timestamps, decisions, reason codes
and object/policy/chain digests. Names, contact data, credential/user handles,
assertion bytes, paths, artifact contents, network addresses and free text are
forbidden. Opaque IDs must not encode personal data.

A closed hash-only deletion receipt binds the bundle, policy, complete storage
inventory, deletion plan and post-deletion scan. `COMPLETE` requires every
expected location attempted, zero failures, zero ordinary backup copies and an
independent witness. `PARTIAL`, `FAILED`, `UNKNOWN`, an incomplete inventory or
shared executor/witness blocks `i09`.

The receipt is deliberately honest: it proves that the declared procedure was
executed over the declared inventory, not mathematical or physical erasure from
all media. Storage design must therefore minimize creation and prevent ordinary
backups before deletion becomes relevant.

No external workspace, audit store, personal data, assertion, receipt or
deletion action exists in this rehearsal. The policy is not implemented, gate
`i09` remains false, and no selection, crypto or runtime/UniFFI permission is
granted.
