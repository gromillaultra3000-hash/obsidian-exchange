# ADR 0010: Checkpoint attestation verifier shortlist

Date: 2026-08-12

Status: Read-only shortlist frozen; dependency installation and verification blocked

## Decision

The future human-review assertion verifier should use the high-level
`webauthn-rs` relying-party API, pinned initially to stable `0.5.5`
(MPL-2.0; crates.io checksum
`6c548915e0e92ee946bbf2aecf01ea21bef53d974b0793cc6732ba81a03fc422`).
Its lower-level core explicitly warns that custom use has security-sensitive
sharp edges. The `attestation` default feature is not required for an already
enrolled assertion and must be evaluated disabled in an isolated dependency
rehearsal. Exact challenge, origin, RP ID, credential ID, ES256, UP, UV,
BE/BS=false and the independent replay ledger remain application policy.

`passkey-rs` `0.5.0` (MIT OR Apache-2.0, revision
`53ca3f9ab146848dfe3ff1e2e93b03b8542de4c3`) is not shortlisted: it implements
the WebAuthn client and authenticator sides, not the relying-party assertion
verification needed here. A hand-built stack from JSON/CBOR/COSE/P-256 crates
is also rejected because it would recreate security-critical WebAuthn rules.

The future automated-review verifier should keep DSSE handling deliberately
small: strict `serde`/`serde_json` data models, `base64` `0.23.1`, a local exact
DSSE 1.0.2 PAE function, and `ed25519-dalek` `3.0.0` with default features off
(BSD-3-Clause; crates.io checksum
`6ebaa1a2bf1290ab3bfe5a7b771d050ebffab2711c19a81691c683a5144a25de`).
Signature verification must cover PAE over the decoded payload bytes; only
those same verified bytes may then be parsed. DSSE `keyid` is only a lookup
hint and cannot select or authorize a root.

`in_toto_attestation` `0.1.0` from in-toto Attestation Framework `v1.2.0`
(Apache-2.0, revision `df02077bf97218a8860a5c534eff1f1381f56984`)
is retained only as a schema-binding candidate. Upstream calls its Rust support
early, unstable and not well tested; it neither verifies DSSE signatures nor
enforces the local SLSA policy. The larger `in-toto` and `sigstore` stacks are
not shortlisted because classic layout verification and online transparency
do not match this minimal independent offline root.

## Conformance sources

No public standards-owned WebAuthn server-verifier vector corpus was found.
W3C web-platform-tests exercise browser/client behavior, and FIDO server
certification tooling is a separate controlled program. Therefore no upstream
library fixture may be mislabeled as official conformance. Before activation,
the project needs an independently reviewed local assertion corpus covering
positive ES256/UV/device-bound cases and every fail-closed field mutation, then
must run the applicable FIDO conformance/certification process.

The automated lane pins these standards-owned sources without vendoring them:

- DSSE `v1.0.2`, revision `440901313676fedd0e31f16125c302b0df81e006`:
  `protocol.md` and its Apache-2.0 reference implementation/doctest vector.
- in-toto Attestation Framework `v1.2.0`, revision
  `df02077bf97218a8860a5c534eff1f1381f56984`: Statement v1 and generated
  language-binding round-trip tests.
- SLSA `v1.2`, revision `19e4e2f005f871270c4f555fc47afecfb37f3efe`:
  provenance schema/examples and verification expectations.
- RFC 8032 Ed25519 test vectors; these must be supplemented by DSSE PAE,
  malformed Base64/JSON, signature/root substitution and parse-after-verify
  mutation cases.

These are source pins, not downloaded fixtures or evidence that an eventual
implementation conforms.

## Security gate

No crate, SDK, parser, credential, root or fixture was installed. Cargo
manifests and the lockfile are unchanged. A later isolated rehearsal must pin
the complete transitive graph, run license/RustSec review, measure platform
build impact, import byte-exact fixtures with SHA-256 provenance, and pass an
independent review before any library or UniFFI surface can be added. All
verification, authentication, acceptance and production-action capabilities
remain false.
