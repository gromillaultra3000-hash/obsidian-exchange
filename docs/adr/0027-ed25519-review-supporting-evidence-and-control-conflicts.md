# ADR 0027: Supporting evidence and control conflicts

Date: 2026-08-15

Status: hash-only bundle and matrix frozen; real evidence prohibited

ADR 0026 authenticates an independence-evidence issuer but does not define what
that issuer must inspect. This record freezes a closed supporting-evidence
manifest and a conflict-of-control matrix. Repository fixtures contain only
opaque domain identifiers, metadata rules and SHA-256 references. Personnel,
credential, registry, recovery, host and operational document bytes remain
external and must never be committed to this rehearsal.

The bundle requires exactly one of fourteen evidence kinds: reviewer control,
credential enrollment/revocation, reviewer recovery, verifier administration/
recovery, result-authentication roots, two builder control registries,
reproducible-build and provenance reports, host failure-domain registry,
evidence-issuer control and the completed conflict matrix. Each entry binds its
subject and issuer domains, digest, capture/expiry times and explicitly declares
that the manifest carries no personal data. Kinds are unique, artifact expiry
must cover bundle expiry, capture cannot be later than bundle issuance and the
bundle lifetime is at most 24 hours. The top-level independence-evidence,
scorecard, issuer-challenge and review-domain bindings are exact; the bundle is
acceptable only with `COMPLETE` completeness and a closed canonical metadata
shape. Real artifact bytes remain external and digest-referenced.

The control matrix checks direct and transitive ability to activate, recover,
revoke, change policy/build inputs, replace runtime or issue evidence for self.
It also checks shared credential, recovery and host roots and undisclosed
delegation. Required separations apply within each review and across both review
domains. Different strings are not proof of separate control.

Only `SEPARATE_WITH_EVIDENCE` passes. `CONFLICT`, `UNKNOWN`, `MISSING`, an absent
or extra row, duplicate required pair, duplicate/missing evidence kind, expired
artifact or incomplete bundle blocks acceptance. The matrix has a closed role
and relationship inventory, evaluates transitive control, and does not permit
a waiver, majority score or compensating control.

No real bundle, matrix, identity, document, credential, root or assertion is
present. Bundle acceptance, issuer authentication, verifier selection, crypto
calls and runtime/UniFFI integration remain false.
