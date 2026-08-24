//! Test-only structural policy for future reviewer attestations.

const MAX_LIFETIME_MS: u64 = 600_000;
const MAX_FUTURE_SKEW_MS: u64 = 1_000;

#[derive(Clone)]
struct Attestation<'a> {
    evidence_id: &'a str,
    reviewer_id: &'a str,
    trust_domain_id: &'a str,
    credential_root_sha256: &'a str,
    recovery_authority_id: &'a str,
    bundle_sha256: &'a str,
    challenge_sha256: &'a str,
    revocation_epoch: u64,
    issued_at_epoch_ms: u64,
    expires_at_epoch_ms: u64,
    automated: bool,
}

struct RevocationSnapshot<'a> {
    epoch: u64,
    revoked_root_sha256: Vec<&'a str>,
}

#[derive(Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit non-authority claims"
)]
struct PolicyReview {
    structure_valid: bool,
    independent_admin_domains_claimed: bool,
    independent_credential_roots_claimed: bool,
    fresh: bool,
    replay_free: bool,
    revocation_current: bool,
    attestations_verified: bool,
    reviewers_authenticated: bool,
    acceptance_allowed: bool,
    keys_installed: bool,
    checkpoint_trusted: bool,
    production_action_allowed: bool,
}

fn sha256_text(value: &str) -> bool {
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

fn review(
    attestations: &[Attestation<'_>; 2],
    snapshot: &RevocationSnapshot<'_>,
    signer_key_ids: &[&str],
    expected_bundle_sha256: &str,
    minimum_revocation_epoch: u64,
    consumed_evidence_ids: &[&str],
    now_epoch_ms: u64,
) -> Result<PolicyReview, String> {
    let [first, second] = attestations;
    if first.reviewer_id >= second.reviewer_id
        || first.trust_domain_id == second.trust_domain_id
        || first.credential_root_sha256 == second.credential_root_sha256
        || first.recovery_authority_id == second.recovery_authority_id
        || first.evidence_id == second.evidence_id
        || (first.automated && second.automated)
        || !attestations.iter().all(|item| {
            opaque_id(item.evidence_id)
                && opaque_id(item.reviewer_id)
                && opaque_id(item.trust_domain_id)
                && opaque_id(item.recovery_authority_id)
                && sha256_text(item.credential_root_sha256)
                && sha256_text(item.bundle_sha256)
                && sha256_text(item.challenge_sha256)
                && item.bundle_sha256 == expected_bundle_sha256
                && !signer_key_ids.contains(&item.reviewer_id)
                && item.revocation_epoch == snapshot.epoch
                && item.issued_at_epoch_ms <= now_epoch_ms.saturating_add(MAX_FUTURE_SKEW_MS)
                && item.expires_at_epoch_ms > now_epoch_ms
                && item.expires_at_epoch_ms > item.issued_at_epoch_ms
                && item.expires_at_epoch_ms - item.issued_at_epoch_ms <= MAX_LIFETIME_MS
                && !consumed_evidence_ids.contains(&item.evidence_id)
                && !snapshot
                    .revoked_root_sha256
                    .contains(&item.credential_root_sha256)
        })
        || snapshot.epoch == 0
        || snapshot.epoch < minimum_revocation_epoch
    {
        return Err("reviewer policy rejected".to_owned());
    }

    Ok(PolicyReview {
        structure_valid: true,
        independent_admin_domains_claimed: true,
        independent_credential_roots_claimed: true,
        fresh: true,
        replay_free: true,
        revocation_current: true,
        attestations_verified: false,
        reviewers_authenticated: false,
        acceptance_allowed: false,
        keys_installed: false,
        checkpoint_trusted: false,
        production_action_allowed: false,
    })
}

const fn fixture() -> [Attestation<'static>; 2] {
    [
        Attestation {
            evidence_id: "evidence_alpha",
            reviewer_id: "reviewer_alpha",
            trust_domain_id: "independent_security",
            credential_root_sha256: "11f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            recovery_authority_id: "security_recovery",
            bundle_sha256: "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            challenge_sha256: "44f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            revocation_epoch: 7,
            issued_at_epoch_ms: 1_786_500_000_000,
            expires_at_epoch_ms: 1_786_500_600_000,
            automated: false,
        },
        Attestation {
            evidence_id: "evidence_bravo",
            reviewer_id: "reviewer_bravo",
            trust_domain_id: "reproducible_build",
            credential_root_sha256: "22f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            recovery_authority_id: "build_recovery",
            bundle_sha256: "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            challenge_sha256: "55f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            revocation_epoch: 7,
            issued_at_epoch_ms: 1_786_500_000_000,
            expires_at_epoch_ms: 1_786_500_600_000,
            automated: true,
        },
    ]
}

const fn snapshot() -> RevocationSnapshot<'static> {
    RevocationSnapshot {
        epoch: 7,
        revoked_root_sha256: Vec::new(),
    }
}

#[test]
fn structurally_valid_claims_remain_non_authoritative() -> Result<(), String> {
    let result = review(
        &fixture(),
        &snapshot(),
        &["signer_alpha", "signer_bravo", "signer_charlie"],
        "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        7,
        &[],
        1_786_500_000_000,
    )?;
    assert!(result.structure_valid);
    assert!(result.independent_admin_domains_claimed);
    assert!(result.independent_credential_roots_claimed);
    assert!(result.fresh);
    assert!(result.replay_free);
    assert!(result.revocation_current);
    assert!(!result.attestations_verified);
    assert!(!result.reviewers_authenticated);
    assert!(!result.acceptance_allowed);
    assert!(!result.keys_installed);
    assert!(!result.checkpoint_trusted);
    assert!(!result.production_action_allowed);
    Ok(())
}

#[test]
fn shared_control_planes_and_double_automation_fail_closed() {
    let mut same_domain = fixture();
    same_domain[1].trust_domain_id = same_domain[0].trust_domain_id;
    assert!(
        review(
            &same_domain,
            &snapshot(),
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            same_domain[0].bundle_sha256,
            7,
            &[],
            same_domain[0].issued_at_epoch_ms
        )
        .is_err()
    );
    let mut same_root = fixture();
    same_root[1].credential_root_sha256 = same_root[0].credential_root_sha256;
    assert!(
        review(
            &same_root,
            &snapshot(),
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            same_root[0].bundle_sha256,
            7,
            &[],
            same_root[0].issued_at_epoch_ms
        )
        .is_err()
    );
    let mut same_recovery = fixture();
    same_recovery[1].recovery_authority_id = same_recovery[0].recovery_authority_id;
    assert!(
        review(
            &same_recovery,
            &snapshot(),
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            same_recovery[0].bundle_sha256,
            7,
            &[],
            same_recovery[0].issued_at_epoch_ms
        )
        .is_err()
    );
    let mut reviewer_overlap = fixture();
    reviewer_overlap[0].reviewer_id = "signer_alpha";
    assert!(
        review(
            &reviewer_overlap,
            &snapshot(),
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            reviewer_overlap[0].bundle_sha256,
            7,
            &[],
            reviewer_overlap[0].issued_at_epoch_ms
        )
        .is_err()
    );
    let mut automated = fixture();
    automated[0].automated = true;
    assert!(
        review(
            &automated,
            &snapshot(),
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            automated[0].bundle_sha256,
            7,
            &[],
            automated[0].issued_at_epoch_ms
        )
        .is_err()
    );
}

#[test]
fn freshness_replay_and_revocation_rollback_fail_closed() {
    let attestations = fixture();
    assert!(
        review(
            &attestations,
            &snapshot(),
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            attestations[0].bundle_sha256,
            7,
            &["evidence_alpha"],
            attestations[0].issued_at_epoch_ms
        )
        .is_err()
    );
    assert!(
        review(
            &attestations,
            &snapshot(),
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            attestations[0].bundle_sha256,
            7,
            &[],
            attestations[0].expires_at_epoch_ms
        )
        .is_err()
    );
    let stale_snapshot = RevocationSnapshot {
        epoch: 6,
        revoked_root_sha256: Vec::new(),
    };
    assert!(
        review(
            &attestations,
            &stale_snapshot,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            attestations[0].bundle_sha256,
            7,
            &[],
            attestations[0].issued_at_epoch_ms
        )
        .is_err()
    );
    let revoked = RevocationSnapshot {
        epoch: 7,
        revoked_root_sha256: vec![attestations[0].credential_root_sha256],
    };
    assert!(
        review(
            &attestations,
            &revoked,
            &["signer_alpha", "signer_bravo", "signer_charlie"],
            attestations[0].bundle_sha256,
            7,
            &[],
            attestations[0].issued_at_epoch_ms
        )
        .is_err()
    );
}
