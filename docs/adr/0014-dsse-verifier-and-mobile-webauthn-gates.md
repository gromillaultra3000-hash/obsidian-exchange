# ADR 0014: DSSE verifier contract and mobile WebAuthn gates

Date: 2026-08-12

Status: Test-only decision contracts frozen; implementations blocked

## Minimal DSSE API

The future automated-review entry point accepts an immutable envelope byte
slice, exact expected context, an externally selected root snapshot and a
read-only replay snapshot. It returns a typed decision and never mutates trust,
replay or checkpoint state. Root selection is by the expected policy/epoch, not
by the unauthenticated DSSE `keyid` hint.

Processing is ordered and fail-closed:

1. Apply envelope byte/depth/field/signature-count limits, parse a strict outer
   JSON object and reject unknown/duplicate fields.
2. Require `application/vnd.in-toto+json`, canonical standard Base64 and exactly
   one 64-byte Ed25519 signature.
3. Resolve the externally expected root epoch and reject unknown, stale or
   revoked roots.
4. Construct DSSE 1.0.2 PAE from the decoded payload type and exact decoded
   payload bytes, then verify the signature over those bytes.
5. Only after signature success, parse those same payload bytes once using
   strict duplicate/unknown-field and resource limits.
6. Enforce Statement v1, SLSA provenance v1, subject/rebuild equality, exact
   builder/build type/source/dependencies/external parameters and freshness/
   replay policy.

No canonicalized or reserialized JSON may replace the signed payload. A valid
signature with invalid policy is rejected. Even complete success returns
`VERIFIED_NON_AUTHORITATIVE`; a separate reviewed quorum decision is still
required.

## Mobile WebAuthn crypto-provider acceptance matrix

The current OpenSSL-backed `webauthn-rs 0.5.5` path fails the matrix and remains
blocked. A candidate must satisfy all criteria on pinned
`aarch64-apple-ios` and `aarch64-linux-android` device targets plus their test
targets:

- locked, offline, warning-free builds without ambient host discovery;
- one documented crypto provider with no silently selected fallback;
- ES256 verification and COSE/DER handling covered by the reviewed corpus;
- reproducible binaries and an explicit measured size budget;
- upstream security policy, supported update path and RustSec/native CVE scan;
- no default vendored OpenSSL and no undeclared dynamic-library dependency;
- complete license/notice obligations for static mobile distribution;
- identical assertion-policy results on iOS, Android and the independent oracle.

Build success alone cannot approve a provider. Every matrix result needs exact
target/toolchain/SDK/lock hashes and reviewer evidence. Until one candidate
passes every row, WebAuthn integration, credentials and reviewer authentication
remain disabled.

## Current boundary

Both matrices are symbolic integration tests. They contain no envelope bytes,
payload bytes, signature bytes, public keys, crypto call, parser dependency,
SDK, credential, trust root, target installation or UniFFI/runtime API. All
authority and production flags remain false.
