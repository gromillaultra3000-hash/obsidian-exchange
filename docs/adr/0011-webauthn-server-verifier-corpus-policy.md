# ADR 0011: WebAuthn server-verifier corpus policy

Date: 2026-08-12

Status: Test-only corpus policy frozen; fixtures and verification blocked

## Context

There is no public standards-owned corpus that proves conformance of a
WebAuthn relying-party assertion verifier. Browser web-platform-tests and
authenticator/CTAP tests cover different trust boundaries. Treating upstream
`webauthn-rs` unit tests as independent evidence would make the implementation
and its oracle share the same assumptions.

## Decision

Create a project-owned, implementation-neutral assertion corpus before adding
the verifier. It must contain only synthetic credentials generated for testing,
never enrolled reviewer credentials. Every fixture is immutable and has:

- a stable case ID and expected accept/reject class;
- raw response bytes plus exact challenge, origin, RP ID and enrolled public
  credential record;
- generator name/version/revision, deterministic recipe and SHA-256;
- standards clauses and the reason for the expected result;
- confirmation by two reviewers who did not author the generator;
- results from the selected Rust verifier and an independently maintained
  oracle using the same raw bytes.

The independent oracle is a differential-testing aid, not authority. A case is
eligible only when the standards-derived expectation was written before either
implementation result was observed. Any disagreement is fail-closed and blocks
release; majority voting between implementations is forbidden.

## Minimum matrix

Positive cases cover ES256 with exact challenge/origin/RP ID/credential ID,
UP+UV, BE=false, BS=false, zero and advancing signature counters, valid DER
ECDSA edge lengths and permitted extra client-data members.

Negative cases independently mutate: type, challenge encoding/value, origin
scheme/host/port/trailing-dot and cross-origin fields; RP-ID hash; credential
ID/type; UP, UV, BE and BS flag combinations; reserved authenticator bits;
authenticator-data length; signature DER structure, high/invalid scalar and
signature bytes; client-data UTF-8/JSON/duplicate keys; algorithm/key type,
curve and coordinate lengths; stale/unknown enrollment; replayed evidence ID;
and payload truncation, extension-data/trailing-byte inconsistencies.

Every negative fixture changes one semantic dimension where possible. Combined
mutations are added only to verify deterministic error precedence. Parsers must
enforce byte/size/depth/count limits before allocation-heavy processing.

## Provenance and independence gates

Generated private keys may exist only inside the offline fixture-generation
workspace and must be destroyed after reproducible generation. They must be
visibly marked test-only and cannot share any reviewer root, RP database or
recovery authority. Checked-in fixtures contain only public keys, assertions
and signatures.

The corpus generator, expected-result manifest and verifier must be separate
artifacts. At least one corpus reviewer must be outside the verifier's
administrative domain. The generation recipe must reproduce every byte from a
pinned toolchain; otherwise the fixture is quarantined.

FIDO conformance/certification remains a release gate when applicable. The
local corpus supplements it with project policy and regression coverage; it
never claims official certification.

## Current boundary

This ADR and its test-only matrix contain no raw assertion, signature, public
credential key, private key, parser, SDK or verifier call. No dependency or
runtime surface is added. Authentication, corpus approval, trust installation,
checkpoint acceptance and production action remain false.
