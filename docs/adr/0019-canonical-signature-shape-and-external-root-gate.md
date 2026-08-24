# ADR 0019: Canonical signature shape and external root gate

Date: 2026-08-12

Status: Isolated signature shape and symbolic root gates pass; crypto blocked

The isolated `automated-minimal` rehearsal now decodes the sole DSSE `sig`
field only after checking its encoded length is exactly 88 bytes. Standard
padded RFC 4648 decoding must yield exactly 64 bytes and re-encoding must match
the original string byte-for-byte. Omitted padding, whitespace, URL-safe
alphabet, non-zero unused bits and decoded-length drift fail. The result is a
fixed-width container with read-only byte access; this operation checks shape
and canonical representation only.

Root policy is modeled separately from the envelope. Callers supply the
expected policy identifier and epoch plus an already externally selected
snapshot containing only policy, epoch and active/revoked status. Validation is
ordered and distinguishes malformed expectation, unknown policy, stale epoch,
unknown future epoch and revoked epoch. The function accepts no `keyid` and no
key bytes. Tests vary absent, matching-looking and attacker-selected DSSE
`keyid` hints and prove that the external root decision is unchanged.

No public key representation, Ed25519 API call, trust-root installation or
signature success exists. `VERIFIER_IMPLEMENTED` remains false; decoded bytes
cannot grant authority, and no native runtime, workspace or UniFFI surface is
changed. Actual verification remains blocked until independently pinned public
vectors, mutation cases and root-key provenance are reviewed.
