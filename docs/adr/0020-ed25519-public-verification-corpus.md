# ADR 0020: Public Ed25519 verification corpus pin

Date: 2026-08-12

Status: Public corpus pinned; cryptographic call remains blocked

The isolated attestation rehearsal now carries one verification-only Ed25519
baseline from RFC 8032 Section 7.1, TEST 2. Only the public key, one-byte
message and signature are copied. The RFC's secret-key field is deliberately
absent. A separate provenance record identifies the RFC Editor source, the
selected section/vector, the errata review date, the IETF Trust licensing
source and the byte-exact SHA-256 of the local corpus.

Seven deterministic, single-field negative recipes cover public-key, message,
signature-R and signature-S bit changes, an all-zero public key and truncated
public-key/signature encodings. They are predeclared as `INVALID`; no result
was learned from the candidate verifier. The recipes contain no generated key
or signature material.

This slice performs structure, provenance, digest and secret-absence checks
only. It does not call `ed25519-dalek`, parse a public key, verify a signature,
install a root or grant authority. The corpus and provenance explicitly keep
crypto calls and runtime integration disabled. Before a cryptographic call is
added, two reviewers must independently compare the public fields with the RFC,
confirm the local digest and licensing treatment, and approve the mutation
expectations. `VERIFIER_IMPLEMENTED` remains false and the native workspace,
runtime and UniFFI surface are unchanged.
