# ADR 0035: Checkpoint witness evidence envelopes

Date: 2026-08-15

Status: bounded import shapes frozen; evidence remains opaque

ADR 0034 defines the slot-specific challenge. This record freezes two closed
transport envelopes for importing candidate witness evidence without enabling
either verifier.

The DSSE envelope binds declared slot/domain/root, checkpoint and challenge
digests, the exact checkpoint-witness payload type, one standard-padded Base64
payload, one opaque Base64 signature, an optional bounded `keyid` hint and the
complete evidence digest. Payload is limited to 8 KiB, signature to 1 KiB and
serialized evidence to 16 KiB. Canonical decoding must reproduce the original
text. `keyid` never selects a root.

The WebAuthn envelope binds the same declared context and the five assertion
byte fields using canonical unpadded Base64URL. Client data is limited to 8 KiB;
credential ID, authenticator data and signature to 1 KiB each; user handle to
64 bytes; and serialized evidence to 16 KiB. User handle alone may be null.

Both are transport containers, not authentication results. Their declared
checkpoint/challenge/root values are untrusted until they match the exact
verified payload or assertion. Structural validity, canonical text and a digest
do not prove signature validity, credential identity, UP/UV, RP/origin, root
status or witness independence.

No payload, signature or assertion decoding; key/credential lookup; verifier;
real evidence; witness enrollment; crypto call; or runtime/UniFFI integration
was added. Checkpoint authentication and gate `i09` remain false.
