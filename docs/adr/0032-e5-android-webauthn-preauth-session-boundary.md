# ADR 0032: Test-only Android/WebAuthn pre-authentication session boundary

Date: 2026-08-22

Status: implemented as a rehearsal boundary; cryptographic authentication blocked

The next bounded E5 slice adds a pure, test-only pre-authentication boundary for
the two-phone procedure. It issues one short-lived challenge session for the
independent reviewer and a different session for the accountable owner. Each
session binds the exact decision-result, owner/reviewer handoff and issuer-
selection scorecard digests, role, human identity, trust domain, RP ID, origin,
timestamps and caller nonce.

The boundary checks closed shape, exact context, role, pairwise independence,
freshness, single-use session/nonce and deterministic challenge/link integrity.
It carries the frozen WebAuthn profile (`WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV`),
UP/UV requirements, `BE=0`, `BS=0`, and flags byte `0x05` as policy inputs.

This is not a WebAuthn verifier. No Android APK, Credential Manager call, RP
endpoint, credential enrollment, public-key registry, ES256 verification,
revocation lookup, network, storage, wallet signing or issuer selection was
added. Every validation result therefore keeps `authenticated`,
`selectionAllowed`, `cryptoCallAllowed` and `runtimeIntegrationAllowed` false.
The generated links use `review.invalid` in tests and are inert examples, not
links to open or enter credentials.

The real next implementation after owner approval is an isolated RP/verifier
with official WebAuthn test vectors, independent enrollment roots and a
single-use assertion ledger. Until that exists, and until both people provide
real authenticated decisions over the exact envelope, E5 remains
`BLOCKED_OWNER`.

Follow-on preflight now accepts the bounded assertion envelope shape, canonical
Base64URL fields, strict client-data JSON, exact 37-byte authenticator data,
RP-ID hash, exact challenge/origin and flags byte `0x05`. It returns only a
hash and boolean shape summary; it never returns assertion bytes. Credential
lookup, revocation, ES256 verification and authentication remain false.

The next RP contract is also pure and inert: a caller-supplied session map is
served through a GET session view and a POST assertion-preflight response.
There is no listening socket, HTTP framework, persistence, replay ledger,
credential enrollment or production route. The POST response explicitly marks
consumption as deferred and all authority flags as false.

A loopback-only HTTPS harness now exists around this adapter. It requires an
explicit TLS certificate/key path and exact HTTPS origin, rejects non-loopback
binds such as 0.0.0.0, and is constructed but never started by the tests. It
is not reachable from the two Android phones; a separately approved staging
domain, certificate and deployment boundary are still required.

The proposed payment alias `pay.obsidianbtc.org` is explicitly excluded. The
current E0.4 inventory classifies it as a public wildcard payment edge with an
unowned/unproven loopback upstream, so it cannot be reused as a WebAuthn RP
without a separate owner-gated payment-edge decision. The local harness accepts
only loopback RP IDs; a future staging subdomain needs its own DNS/TLS and
deployment policy.
