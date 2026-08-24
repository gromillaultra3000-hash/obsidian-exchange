//! Test-only synthetic active checkpoint key-set evidence contract.

use bitcoin::hashes::{Hash, sha256};
use bitcoin::secp256k1::XOnlyPublicKey;

const SCHEMA: &str = "native-checkpoint-active-keyset-evidence.v1";
const ALGORITHM: &str = "BIP340_SECP256K1_XONLY_SHA256";
const COMMITMENT_DOMAIN: &[u8] = b"OBSIDIAN_CHECKPOINT_KEY_COMMITMENT_V1";

#[derive(Clone)]
struct Slot<'a> {
    signer_key_id: &'a str,
    xonly_public_key_hex: &'a str,
}

struct Evidence<'a> {
    ceremony_sha256: &'a str,
    epoch: u32,
    slots: Vec<Slot<'a>>,
    reviewer_ids: [&'a str; 2],
    reviewed_at_epoch_ms: u64,
    content_sha256: String,
}

#[derive(Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit non-authority claims"
)]
struct Review {
    ceremony_content_bound: bool,
    signer_set_matches: bool,
    commitment_set_matches: bool,
    mapping_content_bound: bool,
    reviewer_claims_bound: bool,
    mapping_reviewers_verified: bool,
    keys_installed: bool,
    active_key_authority: bool,
    checkpoint_trusted: bool,
    chain_verified: bool,
    production_action_allowed: bool,
}

fn hex32(value: &str) -> Result<[u8; 32], String> {
    if value.len() != 64
        || !value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
    {
        return Err("non-canonical 32-byte hex".to_owned());
    }
    let mut output = [0_u8; 32];
    for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
        let text = std::str::from_utf8(pair).map_err(|_| "invalid hex text".to_owned())?;
        output[index] = u8::from_str_radix(text, 16).map_err(|_| "invalid hex".to_owned())?;
    }
    Ok(output)
}

fn opaque_id(value: &str) -> bool {
    (8..=64).contains(&value.len())
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-' || byte == b'_'
        })
}

fn key_commitment(key: &[u8; 32]) -> String {
    let mut preimage = Vec::with_capacity(COMMITMENT_DOMAIN.len() + 33);
    preimage.extend_from_slice(COMMITMENT_DOMAIN);
    preimage.push(0);
    preimage.extend_from_slice(key);
    sha256::Hash::hash(&preimage).to_string()
}

fn push_text(payload: &mut Vec<u8>, value: &str) -> Result<(), String> {
    let length = u16::try_from(value.len()).map_err(|_| "text too long".to_owned())?;
    payload.extend_from_slice(&length.to_be_bytes());
    payload.extend_from_slice(value.as_bytes());
    Ok(())
}

fn evidence_digest(evidence: &Evidence<'_>) -> Result<String, String> {
    let mut payload = Vec::new();
    push_text(&mut payload, SCHEMA)?;
    push_text(&mut payload, ALGORITHM)?;
    payload.extend_from_slice(&hex32(evidence.ceremony_sha256)?);
    payload.extend_from_slice(&evidence.epoch.to_be_bytes());
    for slot in &evidence.slots {
        push_text(&mut payload, slot.signer_key_id)?;
        payload.extend_from_slice(&hex32(slot.xonly_public_key_hex)?);
    }
    for reviewer in evidence.reviewer_ids {
        push_text(&mut payload, reviewer)?;
    }
    payload.extend_from_slice(&evidence.reviewed_at_epoch_ms.to_be_bytes());
    Ok(sha256::Hash::hash(&payload).to_string())
}

fn review(
    evidence: &Evidence<'_>,
    ceremony_sha256: &str,
    ceremony_epoch: u32,
    ceremony_key_ids: &[&str],
    ceremony_commitments: &[String],
) -> Result<Review, String> {
    if evidence.ceremony_sha256 != ceremony_sha256
        || evidence.epoch == 0
        || evidence.epoch != ceremony_epoch
        || evidence.reviewed_at_epoch_ms == 0
        || evidence.slots.len() != 3
        || evidence.reviewer_ids[0] >= evidence.reviewer_ids[1]
        || !evidence.reviewer_ids.iter().all(|value| opaque_id(value))
        || evidence
            .slots
            .iter()
            .any(|slot| evidence.reviewer_ids.contains(&slot.signer_key_id))
        || evidence
            .slots
            .windows(2)
            .any(|pair| pair[0].signer_key_id >= pair[1].signer_key_id)
        || !evidence
            .slots
            .iter()
            .all(|slot| opaque_id(slot.signer_key_id))
    {
        return Err("invalid key-set evidence context".to_owned());
    }

    let signer_ids: Vec<&str> = evidence
        .slots
        .iter()
        .map(|slot| slot.signer_key_id)
        .collect();
    if signer_ids != ceremony_key_ids {
        return Err("ceremony signer set mismatch".to_owned());
    }
    let mut commitments = Vec::new();
    for slot in &evidence.slots {
        let key = hex32(slot.xonly_public_key_hex)?;
        XOnlyPublicKey::from_slice(&key).map_err(|_| "invalid x-only public key".to_owned())?;
        commitments.push(key_commitment(&key));
    }
    commitments.sort();
    if commitments != ceremony_commitments {
        return Err("ceremony commitment set mismatch".to_owned());
    }
    if evidence_digest(evidence)? != evidence.content_sha256 {
        return Err("evidence content digest mismatch".to_owned());
    }

    Ok(Review {
        ceremony_content_bound: true,
        signer_set_matches: true,
        commitment_set_matches: true,
        mapping_content_bound: true,
        reviewer_claims_bound: true,
        mapping_reviewers_verified: false,
        keys_installed: false,
        active_key_authority: false,
        checkpoint_trusted: false,
        chain_verified: false,
        production_action_allowed: false,
    })
}

fn slots() -> Vec<Slot<'static>> {
    vec![
        Slot {
            signer_key_id: "signer_alpha",
            xonly_public_key_hex: "25d1dff95105f5253c4022f628a996ad3a0d95fbf21d468a1b33f8c160d8f517",
        },
        Slot {
            signer_key_id: "signer_bravo",
            xonly_public_key_hex: "778caa53b4393ac467774d09497a87224bf9fab6f6e68b23086497324d6fd117",
        },
        Slot {
            signer_key_id: "signer_charlie",
            xonly_public_key_hex: "dff1d77f2a671c5f36183726db2341be58feae1da2deced843240f7b502ba659",
        },
    ]
}

fn fixture() -> (Evidence<'static>, Vec<String>) {
    let slots = slots();
    let mut commitments = slots
        .iter()
        .map(|slot| hex32(slot.xonly_public_key_hex).map(|key| key_commitment(&key)))
        .collect::<Result<Vec<_>, _>>()
        .unwrap_or_default();
    commitments.sort();
    let mut evidence = Evidence {
        ceremony_sha256: "44f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        epoch: 1,
        slots,
        reviewer_ids: ["reviewer_alpha", "reviewer_bravo"],
        reviewed_at_epoch_ms: 1_786_500_000_000,
        content_sha256: String::new(),
    };
    evidence.content_sha256 = evidence_digest(&evidence).unwrap_or_default();
    (evidence, commitments)
}

#[test]
fn binds_mapping_to_ceremony_sets_without_granting_authority() -> Result<(), String> {
    let (evidence, commitments) = fixture();
    let result = review(
        &evidence,
        evidence.ceremony_sha256,
        1,
        &["signer_alpha", "signer_bravo", "signer_charlie"],
        &commitments,
    )?;
    assert!(result.ceremony_content_bound);
    assert!(result.signer_set_matches);
    assert!(result.commitment_set_matches);
    assert!(result.mapping_content_bound);
    assert!(result.reviewer_claims_bound);
    assert!(!result.mapping_reviewers_verified);
    assert!(!result.keys_installed);
    assert!(!result.active_key_authority);
    assert!(!result.checkpoint_trusted);
    assert!(!result.chain_verified);
    assert!(!result.production_action_allowed);
    Ok(())
}

#[test]
fn mapping_permutation_requires_a_new_review_digest() {
    let (mut evidence, commitments) = fixture();
    let first = evidence.slots[0].xonly_public_key_hex;
    evidence.slots[0].xonly_public_key_hex = evidence.slots[1].xonly_public_key_hex;
    evidence.slots[1].xonly_public_key_hex = first;
    assert!(
        review(
            &evidence,
            evidence.ceremony_sha256,
            1,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments,
        )
        .is_err()
    );
}

#[test]
fn ceremony_epoch_signer_commitment_and_key_drift_fail_closed() {
    let (evidence, mut commitments) = fixture();
    assert!(
        review(
            &evidence,
            &"5".repeat(64),
            1,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments
        )
        .is_err()
    );
    assert!(
        review(
            &evidence,
            evidence.ceremony_sha256,
            2,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments
        )
        .is_err()
    );
    assert!(
        review(
            &evidence,
            evidence.ceremony_sha256,
            1,
            &["signer_alpha", "signer_bravo", "signer_delta"],
            &commitments
        )
        .is_err()
    );
    commitments[0] = "6".repeat(64);
    assert!(
        review(
            &evidence,
            evidence.ceremony_sha256,
            1,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments
        )
        .is_err()
    );

    let (mut invalid_key, commitments) = fixture();
    invalid_key.slots[0].xonly_public_key_hex =
        "ffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffffff";
    invalid_key.content_sha256 = evidence_digest(&invalid_key).unwrap_or_default();
    assert!(
        review(
            &invalid_key,
            invalid_key.ceremony_sha256,
            1,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments
        )
        .is_err()
    );
}

#[test]
fn reviewer_overlap_slot_order_and_content_drift_fail_closed() {
    let (mut overlap, commitments) = fixture();
    overlap.reviewer_ids[0] = "signer_alpha";
    overlap.content_sha256 = evidence_digest(&overlap).unwrap_or_default();
    assert!(
        review(
            &overlap,
            overlap.ceremony_sha256,
            1,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments,
        )
        .is_err()
    );

    let (mut duplicate_slot, commitments) = fixture();
    duplicate_slot.slots[1].signer_key_id = "signer_alpha";
    assert!(
        review(
            &duplicate_slot,
            duplicate_slot.ceremony_sha256,
            1,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments,
        )
        .is_err()
    );

    let (mut drifted, commitments) = fixture();
    drifted.reviewed_at_epoch_ms += 1;
    assert!(
        review(
            &drifted,
            drifted.ceremony_sha256,
            1,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            &commitments,
        )
        .is_err()
    );
}
