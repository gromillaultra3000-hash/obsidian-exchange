# ADR 0024: Ed25519 review verifier trust shortlist

Date: 2026-08-15

Status: shortlist and threat model frozen; selection blocked

ADR 0023 deliberately left an external verifier result unauthenticated. This
record separates two claims that must never collapse into one: authenticity of
the exact result bytes, and identity of the verifier build that produced them.
A third claim—whether that build actually executed with the expected policy and
configuration—also remains distinct.

## Result-authentication shortlist

| Option | Useful property | Decisive residual risk | Status |
|---|---|---|---|
| Local pinned execution over a private process boundary | No portable signing key; direct nonce/input binding | A compromised host can replace the process or forge IPC | Shortlisted, not selected |
| DSSE-signed closed result with a dedicated key | Portable offline exact-byte evidence | Key use does not prove which binary executed; independent root/revocation required | Shortlisted, not selected |
| Hardware-backed workload quote | Can bind freshness and measured execution | Vendor roots, incomplete measurements, privacy and platform complexity | Deferred |
| Sigstore keyless bundle | Auditable identity and transparency | OIDC/CA/log control planes and offline checkpoint policy | Supplemental only |

## Build-identity shortlist

Independent reproducibility plus an exact binary digest is a required candidate,
but does not prove execution. in-toto/SLSA/DSSE provenance is also a required
candidate, but does not prove reproducibility or execution. Hardware measurement
may provide execution evidence only when its coverage includes the executable,
policy, mutable dependencies and relevant configuration. A package/container
digest is insufficient alone.

Every future result must cross-bind the review request, assertion envelope,
challenge, evidence ID, credential root, revocation epoch, verifier build and
policy digests, issue/expiry window and a caller nonce. Provenance, byte equality
and execution identity are validated independently and in that order before the
WebAuthn outcome is consumed.

## Threat conclusion

The dominant open threats are a structurally forged result, a valid signer
fronting a modified verifier, build-digest substitution, stale replay, parser
disagreement, and one administrative domain controlling both nominal reviews.
No option simultaneously closes these threats today. Selection requires two
independent reproducible builds, separate compromise/recovery roots, offline
revocation, a single-use nonce/evidence ledger, negative corpus parity and an
explicit configuration-measurement policy.

No mechanism or build source is selected. No key, verifier, assertion,
credential, result, root or runtime surface was added. Reviewer authentication,
Ed25519 verification permission and runtime/UniFFI integration remain false.
