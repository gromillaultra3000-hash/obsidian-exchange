# ADR 0012: Attestation corpus manifest and source provenance

Date: 2026-08-12

Status: Schemas and source hashes frozen; generation and verification blocked

## WebAuthn corpus manifest

Every future fixture must validate against
`webauthn-corpus-manifest.schema.json`. The manifest is deliberately metadata
only: raw assertion bytes live in separately hashed files and private keys are
forbidden. Required fields bind the case ID, expected non-authoritative result,
single mutation dimension, standards clauses, rationale, exact context and
enrollment fingerprints, generator/toolchain identity, deterministic recipe,
artifact SHA-256 values, two independent reviewers and two implementation
results over the same corpus digest.

Expectations must be sealed before implementation results. Reviewer and result
entries require distinct administrative domains. `agreement` may be true only
when both implementations match the pre-sealed expectation; disagreement or a
digest mismatch quarantines the complete corpus. Neither agreement nor review
authorizes authentication or production action.

The future offline generator protocol is:

1. Review and seal the expectation manifest without fixtures or implementation
   results.
2. Build a pinned, network-disabled generator from a reviewed source revision.
3. Generate only synthetic credentials inside an ephemeral encrypted workspace.
4. Re-run from a clean workspace and require byte-identical public artifacts.
5. Destroy private fixture keys and the workspace; verify they are absent from
   the output and repository.
6. Have two non-generator reviewers validate provenance and standards mapping.
7. Run the selected verifier and independent oracle separately over identical
   corpus bytes; quarantine any disagreement.

No generator command or executable is provided yet, so this protocol cannot
accidentally create key material.

## Automated-lane source provenance

`attestation-source-provenance.json` pins five standards-owned documents by
repository revision, immutable raw URL and SHA-256:

- DSSE 1.0.2 protocol and Apache-2.0 reference/doctest vector;
- in-toto Attestation Framework 1.2.0 Statement v1;
- SLSA 1.2 provenance CUE schema and artifact-verification requirements.

The files were hashed directly from revision-addressed upstream content. They
are references, not vendored fixtures, executable dependencies or proof of
conformance. A future vendoring step must independently fetch each URL twice,
verify its declared hash and license, and preserve byte-exact content.

The metadata-only policy additionally requires unique case IDs, two distinct
reviewer IDs and administrative domains, two independent implementation results
over the top-level corpus digest, offline generators, and all authority flags
false. These cross-field checks supplement the JSON Schema; they do not create
an authenticated corpus or verifier.

## Current boundary

There are no assertion bytes, signatures, public/private fixture keys,
credentials, generator, SDK, parser, verifier or trust roots. Cargo manifests,
the lockfile, library sources and UniFFI remain unchanged. All capability flags
remain false.
