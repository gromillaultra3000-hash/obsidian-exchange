# ADR 0015: DSSE parser limits and safe reference fixture

Date: 2026-08-12

Status: Test-only lexical/resource contract frozen; parser and crypto blocked

## Exact limits

The future automated-attestation parser must reject before allocation-heavy
work when any limit is exceeded:

- envelope: 262,144 bytes;
- decoded payload: 196,608 bytes;
- payload type: 128 ASCII bytes;
- outer JSON depth: 4; verified payload JSON depth: 16;
- total JSON tokens: 8,192; any string: 4,096 bytes;
- signatures: exactly 1; decoded signature: exactly 64 bytes;
- optional `keyid` hint: 128 ASCII bytes, never authority;
- subjects: exactly 1; digest entries per resource: at most 4;
- resolved dependencies: at most 256;
- external parameters: at most 32;
- arrays and objects reject duplicate or unknown local-policy fields.

These are application limits, not claims about DSSE/SLSA maxima. Increasing one
requires a new reviewed corpus case and memory/time measurement. Streaming or
preflight counting must prevent a malicious length from causing proportional
allocation before rejection.

## Lexical rules

Envelope and payload JSON must be UTF-8 without BOM. Duplicate keys are rejected
at every depth. Numbers outside the explicitly modeled integer fields, floating
point values, non-finite values and unpaired Unicode surrogates are rejected.
Signed payload bytes are never normalized or reserialized.

DSSE `payload` and `sig` use canonical RFC 4648 standard Base64 only: no URL-safe
alphabet, whitespace or omitted/excess padding; length is divisible by four;
padding appears only at the end; unused padding bits are zero. Decode failure or
re-encoding mismatch rejects the envelope.

## Safe upstream reference handling

The pinned DSSE 1.0.2 `implementation/signing_spec.py` is Apache-2.0 and its
SHA-256 remains independently recorded. Inspection found that it is executable
reference code containing a published test signing scalar. Vendoring the whole
file would create secret-scanner noise and normalize storing private-shaped
material, even though the scalar is public and test-only.

Instead, `dsse-pae-reference-v1.json` contains only the public doctest payload
type, payload and expected PAE text extracted from that pinned file. It contains
no signature, key or executable code and is labeled derived rather than an
official standalone conformance vector. The fixture tests byte construction
only; it cannot test signature verification.

## Current boundary

The Rust contract performs only bounded metadata and Base64 lexical checks plus
public PAE byte construction. ASCII requirements for payload type and optional
`keyid` are explicit lexical gates. It does not parse JSON, decode a signature,
use a crypto dependency, verify a signature or authenticate a builder. Native
Cargo, library sources and UniFFI remain unchanged; all authority flags remain
false.
