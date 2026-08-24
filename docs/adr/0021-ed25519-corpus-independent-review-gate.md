# ADR 0021: Ed25519 corpus independent-review gate

Date: 2026-08-12

Status: Review request frozen; no reviewer responses exist

The public Ed25519 corpus cannot progress to a cryptographic call until two
real reviewers independently approve the exact same inputs. A machine-readable
request now binds the SHA-256 of the corpus, provenance record and ADR 0020,
and lists nine mandatory checks against the primary RFC and licensing source.

The response schema is closed and requires a non-generator reviewer identity,
trust domain, request digest, timestamp, every positive check, an explicit
decision and externally authenticated evidence. The authentication challenge
also binds the exact review timestamp and assertion-envelope digest, while the
pair gate requires positive bounded freshness and future-skew checks. Reviewer
IDs and trust domains must be distinct. Shared identity/domain, generator
identity, evidence/root/recovery/assertion reuse, input drift, a missing or
false check, expired/future evidence or any rejection fails the pair gate.

The authentication scheme is deliberately a placeholder because no reviewer
credential authority has been selected or installed. Consequently even two
structurally complete files cannot yet grant permission. No response or
credential is checked in, and synthetic responses exist only inside negative
unit tests. The request continues to state `crypto_call_allowed:false` and
`runtime_integration_allowed:false`; `ed25519-dalek`, roots, runtime and UniFFI
remain untouched.
