# ADR 0017: Allocation-safe JSON preflight and exact payload Base64

Date: 2026-08-12

Status: Isolated resource preflight and payload decode pass; crypto blocked

The isolated `automated-minimal` rehearsal now applies a single-pass lexical
preflight before every Serde parse. It uses a fixed 16-entry container stack
and scalar counters only: the preflight itself performs no heap allocation.
It enforces the ADR 0015 byte, depth, token and encoded-string limits and
rejects mismatched containers, invalid control characters, invalid escapes and
incomplete strings or Unicode escapes. Exhaustive tests exercise every possible
two-byte input without a panic. This state machine is a resource gate, not a
replacement JSON parser; strict Serde models remain the syntax, duplicate-key
and unknown-field authority.

The outer parser can now decode only `payload` as padded standard RFC 4648
Base64. Encoded length is checked before allocation, decoded length is bounded,
and re-encoding must reproduce the original string byte-for-byte. The returned
vector is therefore the exact payload byte sequence to retain for future DSSE
PAE construction. Tests reject omitted padding, URL-safe alphabet, embedded
whitespace and non-zero unused padding bits.

The `sig` field remains opaque and is never decoded. No PAE, Ed25519 API,
trust root, semantic attestation acceptance, runtime integration or UniFFI
surface exists. `VERIFIER_IMPLEMENTED` remains false and the native Cargo
workspace is unchanged.
