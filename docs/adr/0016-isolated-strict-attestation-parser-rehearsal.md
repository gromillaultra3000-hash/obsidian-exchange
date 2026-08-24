# ADR 0016: Isolated strict attestation parser rehearsal

Date: 2026-08-12

Status: Isolated typed parser and lexical preflight pass; native integration and crypto blocked

The locked `automated-minimal` rehearsal now contains exact local Rust models
for the DSSE outer envelope, in-toto Statement v1 and the selected SLSA
provenance subset. Every object uses Serde `deny_unknown_fields`; generated
struct visitors reject duplicate known fields at outer and nested depths.

Envelope and verified-payload parsing are separate APIs. The payload parser is
documented for use only on the exact bytes returned after future signature
success. BOM, invalid UTF-8, empty input and byte limits fail before typed JSON
deserialization. Exactly one subject/signature, bounded key-id and dependency
counts, and the closed two-field external-parameter model are enforced.

Tests prove rejection of duplicate outer and nested fields, unknown signature
and predicate fields, BOM, invalid UTF-8 and oversize inputs. The rehearsal now
also performs canonical padded Base64 decoding while retaining exact payload
bytes, fixed-width signature Base64 shape decoding, DSSE PAE construction and a
closed URI/digest/dependency-order policy. `ed25519-dalek` is pinned for graph
comparison but is never imported by this source; `VERIFIER_IMPLEMENTED` remains
false.

The allocation-safe lexical preflight enforces the ADR 0015 depth/token/string
limits before Serde. The isolated `automated-minimal` crate passes 11 unit tests
offline, while the `automated-with-schema` comparison profile compiles offline
with zero tests. No signature is verified, no key is selected from `keyid`, no
trust root is installed, and nothing is exposed through native-wallet library
code or UniFFI.
