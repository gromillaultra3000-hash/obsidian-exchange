# ADR 0006: Offline checkpoint key-set review-acceptance bundle

Date: 2026-08-12

Status: Test-only acceptance proposal frozen, authority blocked

## Decision

`native-checkpoint-keyset-review-acceptance.v1` content-binds the exact ceremony
digest, active-key mapping-evidence digest, frozen algorithm-selection digest,
epoch, validity window and two reviewer-attestation claims. Each claim binds a
canonical reviewer ID, an allowlisted trust domain and the SHA-256 of an
external attestation artifact.

The two reviewer IDs must be distinct and sorted; their trust domains must be
distinct and allowlisted. Reviewer IDs must not overlap the three signer slots.
The validity window is strictly positive, bounded to 24 hours, and the observed
time must be inside it. Allowed domains are
`independent_security`, `offline_ceremony_observer` and `reproducible_build`.
The window is non-zero and at most 24 hours. All strings are length-prefixed and
integers are big-endian before SHA-256.

## Non-authority invariant

This bundle proves deterministic content binding and claimed domain separation
only. Attestation hashes are not signatures and reviewer identities are not
authenticated. Success therefore remains
`REVIEW_CLAIMS_BOUND_NON_AUTHORITATIVE`; reviewer authentication, bundle
acceptance, key installation, active authority, checkpoint/chain trust and
production action are false.

The harness is test-only and contains no public/private key bytes, signature
bytes, signing or verification calls. It is absent from wallet library and
UniFFI surfaces.
