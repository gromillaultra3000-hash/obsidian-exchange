# ADR 0038: Public-key shapes and fixture provenance

Date: 2026-08-15

Status: parser requirements and import gate frozen; fixture bytes absent

ADR 0037 binds key-byte digests without defining acceptable public-key shapes.
This record freezes candidate-specific parse requirements and a provenance gate
for future verification-only public fixtures. It adds no key bytes or parser.

An Ed25519 verifying key is exactly 32 RFC 8032 compressed-point bytes. Parsing
must enforce canonical compressed-y encoding, successful on-curve decompression,
torsion-free/non-small-order point semantics and a strict verification API that
rejects non-canonical scalars and weak-key cases. Length and digest equality are
necessary but insufficient. Seed, secret scalar, generation and `keyid`-driven
recovery are forbidden.

An ES256 credential key is at most 256 bytes of deterministic CBOR containing
exactly five COSE labels: `kty=2`, `alg=-7`, `crv=1`, and 32-byte `x`/`y`.
Indefinite lengths, non-shortest encodings, wrong order, duplicates, unknowns,
tags, floats, text keys, trailing bytes and private material fail. Coordinates
must form a finite on-curve NIST P-256 point. Shape and digest alone do not prove
credential ownership or signature validity.

Future fixtures may retain only public verification inputs and expected results.
Each needs an authoritative published source, immutable/document location,
retrieved and retained-field digests, license reference, extraction-procedure
digest and two independently authenticated non-generator reviews. Mutation sets
must cover encoding, point, algorithm/curve, signature and message/signed-data
failures. No fixture enters the repository before every gate passes.

No WebAuthn/FIDO source or license is selected yet, and earlier RFC material is
not automatically reused for this separate checkpoint-witness gate. No public
fixture bytes, private material, parser dependency, point check, crypto call or
runtime/UniFFI integration was added. Checkpoint authentication remains false.
