//! Test-only structural `WebAuthn` assertion envelope.

const EXPECTED_ORIGIN: &str = "https://reviewer.obsidian.invalid";
const EXPECTED_RP_ID_HASH: &str =
    "11f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac";

#[derive(Clone)]
#[allow(clippy::struct_excessive_bools, reason = "exact authenticator flags")]
struct Envelope<'a> {
    schema: &'a str,
    evidence_id: &'a str,
    credential_type: &'a str,
    client_data_type: &'a str,
    challenge_sha256: &'a str,
    origin: &'a str,
    cross_origin: bool,
    rp_id_hash: &'a str,
    user_present: bool,
    user_verified: bool,
    backup_eligible: bool,
    backup_state: bool,
    algorithm: &'a str,
    credential_id_sha256: &'a str,
    credential_public_key_sha256: &'a str,
    client_data_json_sha256: &'a str,
    authenticator_data_sha256: &'a str,
    signature_sha256: &'a str,
    sign_count: u32,
}

#[derive(Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit non-authority claims"
)]
struct Review {
    exact_context_bound: bool,
    up_uv_claimed: bool,
    device_bound_claimed: bool,
    sign_count_advisory_only: bool,
    observed_sign_count: u32,
    signature_verified: bool,
    enrollment_provenance_verified: bool,
    reviewer_authenticated: bool,
    acceptance_allowed: bool,
    production_action_allowed: bool,
}

fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn review(
    envelope: &Envelope<'_>,
    expected_evidence_id: &str,
    expected_challenge: &str,
) -> Result<Review, String> {
    if envelope.schema != "native-checkpoint-webauthn-assertion-envelope.v1"
        || envelope.evidence_id != expected_evidence_id
        || envelope.credential_type != "public-key"
        || envelope.client_data_type != "webauthn.get"
        || envelope.challenge_sha256 != expected_challenge
        || envelope.origin != EXPECTED_ORIGIN
        || envelope.cross_origin
        || envelope.rp_id_hash != EXPECTED_RP_ID_HASH
        || !envelope.user_present
        || !envelope.user_verified
        || envelope.backup_eligible
        || envelope.backup_state
        || envelope.algorithm != "ES256"
        || ![
            envelope.challenge_sha256,
            envelope.rp_id_hash,
            envelope.credential_id_sha256,
            envelope.credential_public_key_sha256,
            envelope.client_data_json_sha256,
            envelope.authenticator_data_sha256,
            envelope.signature_sha256,
        ]
        .iter()
        .all(|value| digest(value))
    {
        return Err("WebAuthn envelope rejected".to_owned());
    }
    Ok(Review {
        exact_context_bound: true,
        up_uv_claimed: true,
        device_bound_claimed: true,
        sign_count_advisory_only: true,
        observed_sign_count: envelope.sign_count,
        signature_verified: false,
        enrollment_provenance_verified: false,
        reviewer_authenticated: false,
        acceptance_allowed: false,
        production_action_allowed: false,
    })
}

const fn fixture() -> Envelope<'static> {
    Envelope {
        schema: "native-checkpoint-webauthn-assertion-envelope.v1",
        evidence_id: "evidence_human_alpha",
        credential_type: "public-key",
        client_data_type: "webauthn.get",
        challenge_sha256: "22f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        origin: EXPECTED_ORIGIN,
        cross_origin: false,
        rp_id_hash: EXPECTED_RP_ID_HASH,
        user_present: true,
        user_verified: true,
        backup_eligible: false,
        backup_state: false,
        algorithm: "ES256",
        credential_id_sha256: "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        credential_public_key_sha256: "44f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        client_data_json_sha256: "55f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        authenticator_data_sha256: "66f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        signature_sha256: "77f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        sign_count: 0,
    }
}

#[test]
fn exact_envelope_remains_non_authoritative() -> Result<(), String> {
    let envelope = fixture();
    let result = review(&envelope, envelope.evidence_id, envelope.challenge_sha256)?;
    assert!(result.exact_context_bound);
    assert!(result.up_uv_claimed);
    assert!(result.device_bound_claimed);
    assert!(result.sign_count_advisory_only);
    assert!(!result.signature_verified);
    assert!(!result.enrollment_provenance_verified);
    assert!(!result.reviewer_authenticated);
    assert!(!result.acceptance_allowed);
    assert!(!result.production_action_allowed);
    Ok(())
}

#[test]
fn context_flag_and_digest_drift_fail_closed() {
    let mut cases = Vec::new();
    let mut origin = fixture();
    origin.origin = "https://attacker.invalid";
    cases.push(origin);
    let mut evidence_id = fixture();
    evidence_id.evidence_id = "evidence_human_bravo";
    cases.push(evidence_id);
    let mut cross_origin = fixture();
    cross_origin.cross_origin = true;
    cases.push(cross_origin);
    let mut uv = fixture();
    uv.user_verified = false;
    cases.push(uv);
    let mut backup = fixture();
    backup.backup_eligible = true;
    cases.push(backup);
    let mut algorithm = fixture();
    algorithm.algorithm = "RS256";
    cases.push(algorithm);
    let mut malformed = fixture();
    malformed.signature_sha256 = "invalid";
    cases.push(malformed);
    for case in cases {
        let expected = fixture();
        assert!(review(&case, expected.evidence_id, expected.challenge_sha256).is_err());
    }
}

#[test]
fn zero_and_nonzero_sign_counts_are_equally_non_authoritative() -> Result<(), String> {
    let zero_fixture = fixture();
    let zero = review(
        &zero_fixture,
        zero_fixture.evidence_id,
        zero_fixture.challenge_sha256,
    )?;
    let mut advanced = fixture();
    advanced.sign_count = 42;
    let nonzero = review(&advanced, advanced.evidence_id, advanced.challenge_sha256)?;
    assert_eq!(zero.observed_sign_count, 0);
    assert_eq!(nonzero.observed_sign_count, 42);
    assert!(zero.sign_count_advisory_only);
    assert!(nonzero.sign_count_advisory_only);
    assert!(!nonzero.reviewer_authenticated);
    Ok(())
}
