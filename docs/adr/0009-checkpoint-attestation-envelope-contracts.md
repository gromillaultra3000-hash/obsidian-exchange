# ADR 0009: Synthetic checkpoint attestation envelope contracts

Date: 2026-08-12

Status: Test-only structural envelopes frozen, cryptographic verification blocked

## Human WebAuthn envelope

`native-checkpoint-webauthn-assertion-envelope.v1` binds the caller-supplied
reviewer evidence ID and exact bundle challenge to `webauthn.get`, an allowlisted HTTPS origin,
RP-ID hash, `public-key` credential type, pinned credential/public-key
fingerprints, ES256, UP and UV. Backup eligibility/state and cross-origin use
must be false. `signCount` is recorded but not used as replay authorization.

The envelope stores only SHA-256 digests of authenticator data, client data and
signature bytes. Structural success leaves signature, enrollment provenance and
reviewer authentication false.

## Automated provenance envelope

`native-checkpoint-build-attestation-envelope.v1` binds DSSE payload type
`application/vnd.in-toto+json`, in-toto Statement v1, SLSA provenance v1,
subject name/digest, exact builder/build type, canonical source URI/revision,
sorted dependency digests, allowlisted external parameters, DSSE payload digest,
Ed25519 root fingerprint and signature digest. The subject digest must equal an
independently supplied rebuild digest passed to the review boundary; equality
with a second field inside the envelope is insufficient by itself.

Unknown external parameters, dependency order/duplication, source, builder,
build type, predicate, subject, payload type or digest drift fail closed. DSSE
`keyid` is not modeled as authority. Structural equality does not prove the
build occurred or that the signature/root is authentic.

## Non-authority invariant

Both contracts exist only in integration tests. They contain no signature bytes,
credential public keys, parser dependency, SDK call or verifier. All
cryptographic verification, reviewer authentication, acceptance, key install,
checkpoint trust and production action flags remain false.
