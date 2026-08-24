//! Test-only application message-binding contract for future checkpoint approvals.

use bitcoin::hashes::{Hash, sha256};

const DOMAIN: &str = "OBSIDIAN_CHECKPOINT_APPROVAL_V1";
const SCHEMA: &str = "native-checkpoint-approval-signature-message.v1";
const ALGORITHM: &str = "BIP340_SECP256K1_XONLY_SHA256";

#[derive(Clone)]
struct Binding<'a> {
    approval_sha256: &'a str,
    artifact_sha256: &'a str,
    ceremony_sha256: &'a str,
    key_epoch: u32,
    signer_key_id: &'a str,
    expires_at_epoch_ms: u64,
}

fn decode_sha256(value: &str) -> Result<[u8; 32], String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("non-canonical SHA-256".to_owned());
    }
    let mut decoded = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let text = std::str::from_utf8(pair).map_err(|_| "invalid SHA-256 text".to_owned())?;
        decoded[index] =
            u8::from_str_radix(text, 16).map_err(|_| "invalid SHA-256 hex".to_owned())?;
    }
    Ok(decoded)
}

fn push_text(payload: &mut Vec<u8>, value: &str) -> Result<(), String> {
    let length = u16::try_from(value.len()).map_err(|_| "text field too long".to_owned())?;
    payload.extend_from_slice(&length.to_be_bytes());
    payload.extend_from_slice(value.as_bytes());
    Ok(())
}

fn payload(binding: &Binding<'_>) -> Result<Vec<u8>, String> {
    if !(8..=64).contains(&binding.signer_key_id.len())
        || !binding.signer_key_id.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-' || byte == b'_'
        })
        || binding.key_epoch == 0
        || binding.expires_at_epoch_ms == 0
    {
        return Err("invalid binding context".to_owned());
    }
    let mut payload = Vec::new();
    push_text(&mut payload, SCHEMA)?;
    push_text(&mut payload, ALGORITHM)?;
    payload.extend_from_slice(&decode_sha256(binding.approval_sha256)?);
    payload.extend_from_slice(&decode_sha256(binding.artifact_sha256)?);
    payload.extend_from_slice(&decode_sha256(binding.ceremony_sha256)?);
    payload.extend_from_slice(&binding.key_epoch.to_be_bytes());
    push_text(&mut payload, binding.signer_key_id)?;
    payload.extend_from_slice(&binding.expires_at_epoch_ms.to_be_bytes());
    Ok(payload)
}

fn tagged_digest(domain: &str, binding: &Binding<'_>) -> Result<[u8; 32], String> {
    if domain != DOMAIN {
        return Err("unsupported application message domain".to_owned());
    }
    let tag_hash = sha256::Hash::hash(domain.as_bytes()).to_byte_array();
    let mut preimage = Vec::with_capacity(64 + 256);
    preimage.extend_from_slice(&tag_hash);
    preimage.extend_from_slice(&tag_hash);
    preimage.extend_from_slice(&payload(binding)?);
    Ok(sha256::Hash::hash(&preimage).to_byte_array())
}

const fn fixture() -> Binding<'static> {
    Binding {
        approval_sha256: "11f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        artifact_sha256: "22f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        ceremony_sha256: "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        key_epoch: 1,
        signer_key_id: "signer_alpha",
        expires_at_epoch_ms: 1_786_500_000_000,
    }
}

#[test]
fn freezes_one_deterministic_application_message() -> Result<(), String> {
    let digest = tagged_digest(DOMAIN, &fixture())?;
    assert_eq!(
        digest,
        [
            0x46, 0xc7, 0x3b, 0x85, 0x96, 0x06, 0xa2, 0x8f, 0xed, 0x7e, 0x9d, 0x4a, 0x3a, 0x11,
            0x8e, 0x7a, 0xd1, 0x07, 0xa3, 0x71, 0xc0, 0x15, 0xb2, 0x69, 0x50, 0xf8, 0x02, 0x9c,
            0xf0, 0x12, 0x41, 0x67,
        ]
    );
    Ok(())
}

#[test]
fn every_bound_field_and_domain_changes_the_message() -> Result<(), String> {
    let original = fixture();
    let expected = tagged_digest(DOMAIN, &original)?;
    let mutations = [
        Binding {
            approval_sha256: "01f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            ..original.clone()
        },
        Binding {
            artifact_sha256: "02f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            ..original.clone()
        },
        Binding {
            ceremony_sha256: "03f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            ..original.clone()
        },
        Binding {
            key_epoch: 2,
            ..original.clone()
        },
        Binding {
            signer_key_id: "signer_bravo",
            ..original.clone()
        },
        Binding {
            expires_at_epoch_ms: original.expires_at_epoch_ms + 1,
            ..original.clone()
        },
    ];
    for mutation in mutations {
        assert_ne!(tagged_digest(DOMAIN, &mutation)?, expected);
    }
    assert!(tagged_digest("OBSIDIAN_CHECKPOINT_APPROVAL_V2", &original).is_err());
    Ok(())
}

#[test]
fn malformed_context_fails_before_digest_derivation() {
    let original = fixture();
    assert!(
        tagged_digest(
            DOMAIN,
            &Binding {
                approval_sha256: "11F0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
                ..original.clone()
            }
        )
        .is_err()
    );
    assert!(
        tagged_digest(
            DOMAIN,
            &Binding {
                signer_key_id: "SignerAlpha",
                ..original.clone()
            }
        )
        .is_err()
    );
    assert!(
        tagged_digest(
            DOMAIN,
            &Binding {
                key_epoch: 0,
                ..original.clone()
            }
        )
        .is_err()
    );
    assert!(
        tagged_digest(
            DOMAIN,
            &Binding {
                expires_at_epoch_ms: 0,
                ..original
            }
        )
        .is_err()
    );
    assert!(
        tagged_digest(
            DOMAIN,
            &Binding {
                signer_key_id: &"a".repeat(65),
                ..original.clone()
            }
        )
        .is_err()
    );
}

#[test]
fn length_prefixes_prevent_text_boundary_ambiguity() -> Result<(), String> {
    let mut first = Vec::new();
    push_text(&mut first, "ab")?;
    push_text(&mut first, "c")?;
    let mut second = Vec::new();
    push_text(&mut second, "a")?;
    push_text(&mut second, "bc")?;
    assert_ne!(first, second);
    Ok(())
}
