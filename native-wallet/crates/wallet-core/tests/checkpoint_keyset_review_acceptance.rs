//! Test-only non-authoritative review-acceptance bundle contract.

use bitcoin::hashes::{Hash, sha256};

const SCHEMA: &str = "native-checkpoint-keyset-review-acceptance.v1";
const STATUS: &str = "REVIEW_CLAIMS_BOUND_NON_AUTHORITATIVE";
const MAX_WINDOW_MS: u64 = 86_400_000;
const ALLOWED_DOMAINS: [&str; 3] = [
    "independent_security",
    "offline_ceremony_observer",
    "reproducible_build",
];

#[derive(Clone)]
struct ReviewerClaim<'a> {
    reviewer_id: &'a str,
    trust_domain: &'a str,
    attestation_sha256: &'a str,
}

struct Bundle<'a> {
    ceremony_sha256: &'a str,
    mapping_evidence_sha256: &'a str,
    algorithm_selection_sha256: &'a str,
    epoch: u32,
    signer_key_ids: [&'a str; 3],
    reviewer_claims: [ReviewerClaim<'a>; 2],
    issued_at_epoch_ms: u64,
    expires_at_epoch_ms: u64,
    content_sha256: String,
}

#[derive(Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit non-authority claims"
)]
struct Review {
    status: &'static str,
    ceremony_bound: bool,
    mapping_evidence_bound: bool,
    algorithm_selection_bound: bool,
    epoch_bound: bool,
    reviewer_claims_bound: bool,
    distinct_trust_domains_claimed: bool,
    reviewers_authenticated: bool,
    bundle_accepted: bool,
    keys_installed: bool,
    active_key_authority: bool,
    checkpoint_trusted: bool,
    chain_verified: bool,
    production_action_allowed: bool,
}

fn canonical_sha256(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn opaque_id(value: &str) -> bool {
    (8..=64).contains(&value.len())
        && value.bytes().all(|byte| {
            byte.is_ascii_lowercase() || byte.is_ascii_digit() || byte == b'-' || byte == b'_'
        })
}

fn push_text(payload: &mut Vec<u8>, value: &str) -> Result<(), String> {
    let length = u16::try_from(value.len()).map_err(|_| "text too long".to_owned())?;
    payload.extend_from_slice(&length.to_be_bytes());
    payload.extend_from_slice(value.as_bytes());
    Ok(())
}

fn digest(bundle: &Bundle<'_>) -> Result<String, String> {
    let mut payload = Vec::new();
    push_text(&mut payload, SCHEMA)?;
    for value in [
        bundle.ceremony_sha256,
        bundle.mapping_evidence_sha256,
        bundle.algorithm_selection_sha256,
    ] {
        if !canonical_sha256(value) {
            return Err("non-canonical bound digest".to_owned());
        }
        push_text(&mut payload, value)?;
    }
    payload.extend_from_slice(&bundle.epoch.to_be_bytes());
    for signer in bundle.signer_key_ids {
        push_text(&mut payload, signer)?;
    }
    for claim in &bundle.reviewer_claims {
        push_text(&mut payload, claim.reviewer_id)?;
        push_text(&mut payload, claim.trust_domain)?;
        push_text(&mut payload, claim.attestation_sha256)?;
    }
    payload.extend_from_slice(&bundle.issued_at_epoch_ms.to_be_bytes());
    payload.extend_from_slice(&bundle.expires_at_epoch_ms.to_be_bytes());
    Ok(sha256::Hash::hash(&payload).to_string())
}

fn review(
    bundle: &Bundle<'_>,
    ceremony_sha256: &str,
    mapping_evidence_sha256: &str,
    algorithm_selection_sha256: &str,
    epoch: u32,
    observed_at_epoch_ms: u64,
) -> Result<Review, String> {
    if bundle.ceremony_sha256 != ceremony_sha256
        || bundle.mapping_evidence_sha256 != mapping_evidence_sha256
        || bundle.algorithm_selection_sha256 != algorithm_selection_sha256
        || bundle.epoch == 0
        || bundle.epoch != epoch
        || bundle.issued_at_epoch_ms == 0
        || bundle.expires_at_epoch_ms <= bundle.issued_at_epoch_ms
        || bundle.expires_at_epoch_ms - bundle.issued_at_epoch_ms > MAX_WINDOW_MS
        || observed_at_epoch_ms < bundle.issued_at_epoch_ms
        || observed_at_epoch_ms >= bundle.expires_at_epoch_ms
        || bundle
            .signer_key_ids
            .windows(2)
            .any(|pair| pair[0] >= pair[1])
        || !bundle.signer_key_ids.iter().all(|value| opaque_id(value))
    {
        return Err("invalid acceptance context".to_owned());
    }
    let [first, second] = &bundle.reviewer_claims;
    if first.reviewer_id >= second.reviewer_id
        || first.trust_domain == second.trust_domain
        || ![first, second].iter().all(|claim| {
            opaque_id(claim.reviewer_id)
                && ALLOWED_DOMAINS.contains(&claim.trust_domain)
                && canonical_sha256(claim.attestation_sha256)
                && !bundle.signer_key_ids.contains(&claim.reviewer_id)
        })
        || digest(bundle)? != bundle.content_sha256
    {
        return Err("invalid reviewer claims".to_owned());
    }

    Ok(Review {
        status: STATUS,
        ceremony_bound: true,
        mapping_evidence_bound: true,
        algorithm_selection_bound: true,
        epoch_bound: true,
        reviewer_claims_bound: true,
        distinct_trust_domains_claimed: true,
        reviewers_authenticated: false,
        bundle_accepted: false,
        keys_installed: false,
        active_key_authority: false,
        checkpoint_trusted: false,
        chain_verified: false,
        production_action_allowed: false,
    })
}

fn fixture() -> Bundle<'static> {
    let mut bundle = Bundle {
        ceremony_sha256: "11f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        mapping_evidence_sha256: "22f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        algorithm_selection_sha256: "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        epoch: 1,
        signer_key_ids: ["signer_alpha", "signer_bravo", "signer_charlie"],
        reviewer_claims: [
            ReviewerClaim {
                reviewer_id: "reviewer_alpha",
                trust_domain: "independent_security",
                attestation_sha256: "44f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            },
            ReviewerClaim {
                reviewer_id: "reviewer_bravo",
                trust_domain: "reproducible_build",
                attestation_sha256: "55f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            },
        ],
        issued_at_epoch_ms: 1_786_500_000_000,
        expires_at_epoch_ms: 1_786_586_400_000,
        content_sha256: String::new(),
    };
    bundle.content_sha256 = digest(&bundle).unwrap_or_default();
    bundle
}

#[test]
fn binds_complete_bundle_without_accepting_it() -> Result<(), String> {
    let bundle = fixture();
    let result = review(
        &bundle,
        bundle.ceremony_sha256,
        bundle.mapping_evidence_sha256,
        bundle.algorithm_selection_sha256,
        1,
        bundle.issued_at_epoch_ms,
    )?;
    assert_eq!(result.status, STATUS);
    assert!(result.ceremony_bound);
    assert!(result.mapping_evidence_bound);
    assert!(result.algorithm_selection_bound);
    assert!(result.epoch_bound);
    assert!(result.reviewer_claims_bound);
    assert!(result.distinct_trust_domains_claimed);
    assert!(!result.reviewers_authenticated);
    assert!(!result.bundle_accepted);
    assert!(!result.keys_installed);
    assert!(!result.active_key_authority);
    assert!(!result.checkpoint_trusted);
    assert!(!result.chain_verified);
    assert!(!result.production_action_allowed);
    Ok(())
}

#[test]
fn digest_epoch_window_and_time_drift_fail_closed() {
    let bundle = fixture();
    assert!(
        review(
            &bundle,
            &"9".repeat(64),
            bundle.mapping_evidence_sha256,
            bundle.algorithm_selection_sha256,
            1,
            bundle.issued_at_epoch_ms
        )
        .is_err()
    );
    assert!(
        review(
            &bundle,
            bundle.ceremony_sha256,
            bundle.mapping_evidence_sha256,
            bundle.algorithm_selection_sha256,
            2,
            bundle.issued_at_epoch_ms
        )
        .is_err()
    );
    assert!(
        review(
            &bundle,
            bundle.ceremony_sha256,
            bundle.mapping_evidence_sha256,
            bundle.algorithm_selection_sha256,
            1,
            bundle.expires_at_epoch_ms
        )
        .is_err()
    );

    let mut oversized = fixture();
    oversized.expires_at_epoch_ms += 1;
    oversized.content_sha256 = digest(&oversized).unwrap_or_default();
    assert!(
        review(
            &oversized,
            oversized.ceremony_sha256,
            oversized.mapping_evidence_sha256,
            oversized.algorithm_selection_sha256,
            1,
            oversized.issued_at_epoch_ms
        )
        .is_err()
    );
}

#[test]
fn same_domain_signer_overlap_and_claim_drift_fail_closed() {
    let mut same_domain = fixture();
    same_domain.reviewer_claims[1].trust_domain = "independent_security";
    same_domain.content_sha256 = digest(&same_domain).unwrap_or_default();
    assert!(
        review(
            &same_domain,
            same_domain.ceremony_sha256,
            same_domain.mapping_evidence_sha256,
            same_domain.algorithm_selection_sha256,
            1,
            same_domain.issued_at_epoch_ms
        )
        .is_err()
    );

    let mut overlap = fixture();
    overlap.reviewer_claims[0].reviewer_id = "signer_alpha";
    overlap.content_sha256 = digest(&overlap).unwrap_or_default();
    assert!(
        review(
            &overlap,
            overlap.ceremony_sha256,
            overlap.mapping_evidence_sha256,
            overlap.algorithm_selection_sha256,
            1,
            overlap.issued_at_epoch_ms
        )
        .is_err()
    );

    let mut drift = fixture();
    drift.reviewer_claims[0].attestation_sha256 =
        "6666666666666666666666666666666666666666666666666666666666666666";
    assert!(
        review(
            &drift,
            drift.ceremony_sha256,
            drift.mapping_evidence_sha256,
            drift.algorithm_selection_sha256,
            1,
            drift.issued_at_epoch_ms
        )
        .is_err()
    );

    let mut unknown_domain = fixture();
    unknown_domain.reviewer_claims[0].trust_domain = "unknown_domain";
    unknown_domain.content_sha256 = digest(&unknown_domain).unwrap_or_default();
    assert!(
        review(
            &unknown_domain,
            unknown_domain.ceremony_sha256,
            unknown_domain.mapping_evidence_sha256,
            unknown_domain.algorithm_selection_sha256,
            1,
            unknown_domain.issued_at_epoch_ms,
        )
        .is_err()
    );

    let mut unsorted_reviewers = fixture();
    unsorted_reviewers.reviewer_claims.swap(0, 1);
    unsorted_reviewers.content_sha256 = digest(&unsorted_reviewers).unwrap_or_default();
    assert!(
        review(
            &unsorted_reviewers,
            unsorted_reviewers.ceremony_sha256,
            unsorted_reviewers.mapping_evidence_sha256,
            unsorted_reviewers.algorithm_selection_sha256,
            1,
            unsorted_reviewers.issued_at_epoch_ms,
        )
        .is_err()
    );

    let mut zero_window = fixture();
    zero_window.expires_at_epoch_ms = zero_window.issued_at_epoch_ms;
    zero_window.content_sha256 = digest(&zero_window).unwrap_or_default();
    assert!(
        review(
            &zero_window,
            zero_window.ceremony_sha256,
            zero_window.mapping_evidence_sha256,
            zero_window.algorithm_selection_sha256,
            1,
            zero_window.issued_at_epoch_ms,
        )
        .is_err()
    );

    let mut before_window = fixture();
    before_window.content_sha256 = digest(&before_window).unwrap_or_default();
    assert!(
        review(
            &before_window,
            before_window.ceremony_sha256,
            before_window.mapping_evidence_sha256,
            before_window.algorithm_selection_sha256,
            1,
            before_window.issued_at_epoch_ms - 1,
        )
        .is_err()
    );
}
