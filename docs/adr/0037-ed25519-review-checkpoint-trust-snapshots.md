# ADR 0037: Checkpoint witness trust snapshots

Date: 2026-08-15

Status: metadata and rotation contracts frozen; key bytes absent

ADR 0036 stops before root and credential lookup. This record freezes closed,
consumer-selected metadata snapshots for each checkpoint witness candidate.
Selection is exclusively by expected policy, witness slot/domain and epoch.
An envelope `keyid`, declared root or assertion credential ID may only be
compared after selection; none can choose authority.

The DSSE snapshot binds root record and Ed25519 public-key-byte digests,
validity/status, recovery authority and predecessor. The WebAuthn snapshot binds
credential ID and COSE public-key-byte digests, ES256/public-key type, exact RP
ID/origin, non-backup eligibility, enrollment provenance, optional user-handle
digest, validity/status, recovery authority and predecessor. Neither schema
contains public-key, credential or personal bytes.

Validation selects the expectation first, parses a closed snapshot, checks exact
policy/slot/domain/epoch, active status and validity, then compares evidence and
stored byte digests. Only after candidate-specific metadata and recovery-domain
separation may key parsing and signature verification run.

Rotation is a separate reviewed operation: epoch strictly advances, predecessor
equals the highest accepted snapshot, authentication material changes, two
independent recovery domains bind the new snapshot, and the old snapshot becomes
revoked/compromised atomically. A failed rotation exposes neither a new active
snapshot nor rollback. Old material remains permanently rejected.

No snapshot store, root, credential, public-key bytes, parser, rotation,
signature verification, checkpoint acceptance, crypto call or runtime/UniFFI
integration exists. Gate `i09` remains false.
