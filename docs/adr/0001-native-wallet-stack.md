# ADR-0001: Native wallet technology stack

Status: accepted for hermetic scaffold; production signing is not authorized.

## Decision

Build separate Swift/SwiftUI and Kotlin/Jetpack Compose shells around a small
Rust wallet core exposed through UniFFI. Deliver one complete Bitcoin Signet
vertical slice before adding mainnet or another chain. Keep transaction parsing,
canonical human-readable summaries, policy checks and later signing inside the
shared core; keep biometrics, hardware-backed wrapping and app integrity in the
native platform adapters.

Bitcoin uses secp256k1, while the portable platform hardware APIs do not provide
a truthful hardware-native secp256k1 guarantee. The wallet secret therefore
uses a hardware-wrapped software-key model: generated on device, ciphertext at
rest, unwrapped only after local authorization into bounded process memory, and
zeroized after success or failure. Secure Enclave/Android Keystore keys are
non-exportable wrapping/authentication keys, not falsely described as Bitcoin
signing keys. The server never receives wallet secrets.

App Attest and Play Integrity are server-verified risk signals. They cannot
authorize signing, replace local confirmation or silently block recovery.

## Competitive advantages

- one audited transaction/policy implementation across both native clients;
- native accessibility, lifecycle, secure UI and platform authentication;
- exact signed-preimage-to-display binding and fail-closed network separation;
- recovery independent of the server, with delayed guardian fallback;
- deterministic fixtures, reproducible release evidence and narrow dependency
  surface instead of a large multi-chain SDK;
- Signet-first vertical delivery with explicit promotion gates.

## Non-goals for the scaffold

No seed generation, key derivation, signing, broadcast, mainnet, real platform
attestation claim or production endpoint is authorized by this ADR. The first
scaffold pins Rust 1.97.1 and UniFFI 0.32.0 with a committed Cargo lockfile.
RustSec audit remains an explicit incomplete gate until `cargo-audit` can be
built and run in a suitable isolated build environment.
