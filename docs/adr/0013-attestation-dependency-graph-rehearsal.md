# ADR 0013: Attestation dependency-graph rehearsal

Date: 2026-08-12

Status: Isolated graphs measured; native-wallet integration blocked

## Method

Three standalone Cargo packages under `native-wallet/rehearsals` each declare
their own empty workspace, so none can become a member or dependency of the
native-wallet workspace. Exact direct versions and generated lockfiles are
retained for reproducibility. The packages expose only
`VERIFIER_IMPLEMENTED = false`; they contain no parser or verifier call.

All three locks pass the locally cached RustSec database (1,211 advisories) and
all registry packages declare a license. Counts below exclude the rehearsal
package itself.

## Results

| Profile | Registry packages | Host check | Main impact |
| --- | ---: | --- | --- |
| Human RP: `webauthn-rs 0.5.5` | 116 | Blocked | system OpenSSL and `pkg-config` required |
| Automated minimal | 36 | Passed | pure Rust crypto/data graph |
| Automated plus in-toto schema | 83 | Passed | +47 packages and protobuf code generation |

The human graph's `openssl-sys 0.9.117` is reached through both
`webauthn-rs-core` and `webauthn-attestation-ca`. Disabling the high-level
crate's default features does not remove it. The clean host check failed because
`pkg-config` and OpenSSL development discovery are absent. Installing host
packages or enabling a vendored OpenSSL build would hide, not solve, the future
iOS/Android linking and update problem. MPL-2.0 and selectable compound-license
obligations also require distribution review before use.

The minimal automated graph uses exact `base64 0.23.1`, `ed25519-dalek 3.0.0`,
`serde 1.0.228` and `serde_json 1.0.145`, with default features disabled and no
missing license metadata. It compiled offline on the pinned Rust 1.97.1 host.

Adding `in_toto_attestation 0.1.0` pulls `protobuf`, `protobuf-codegen`, regex,
temporary-file/platform support and 47 more registry packages. Its build works,
but this cost is not justified while the upstream Rust binding is explicitly
early and the project needs a narrow Statement/SLSA policy rather than the full
generated schema family.

## Decision

Keep `automated-minimal` as the only implementation candidate. Retain
`automated-with-schema` solely as a rejected/deferred comparison until strict
local data models prove insufficient.

Keep `webauthn-rs 0.5.5` as the semantic RP reference but block integration.
Before reconsideration it must pass locked builds and assertion-only tests for
both pinned iOS and Android targets with a documented crypto-provider/update
strategy and license review. Do not install system build packages merely to
make this rehearsal green, and do not introduce vendored OpenSSL into the
mobile core by default.

The metadata-only boundary audit now binds every profile's lock SHA-256 and
registry-package count to `RESULTS.json`, checks exact direct dependency
versions and rejects path/git dependencies. Each rehearsal remains its own
empty Cargo workspace; the native-wallet workspace member list and lockfile
contain none of the rehearsal package roots or the human/schema comparison
dependencies. The minimal parser source has no network/process imports and
keeps all verifier, trust-root and production-action flags false.

## Non-authority boundary

The rehearsal locks are not approved product dependencies. Native-wallet
`Cargo.toml`, `Cargo.lock`, library sources and UniFFI are unchanged. No
credential, key, assertion, signature verification, trust root, network call or
production action exists.
