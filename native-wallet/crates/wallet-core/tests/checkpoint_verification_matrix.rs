//! Test-only decision matrix for future checkpoint approval verification.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum FixtureSignatureOutcome {
    Valid,
    Invalid,
    Malformed,
}

#[derive(Clone, Copy)]
struct Claim<'a> {
    signer_key_id: &'a str,
    outcome: FixtureSignatureOutcome,
}

struct DecisionInput<'a> {
    binding_valid: bool,
    requested_epoch: u32,
    active_epoch: Option<u32>,
    expired: bool,
    active_signer_ids: [&'a str; 3],
    claims: Vec<Claim<'a>>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum DecisionCode {
    MalformedBinding,
    UnknownKeyEpoch,
    StaleKeyEpoch,
    ExpiredApproval,
    UnknownSigner,
    DuplicateSigner,
    MalformedSignature,
    InvalidSignature,
    InsufficientQuorum,
    QuorumSatisfiedNonAuthoritative,
}

#[derive(Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit non-authority claims"
)]
struct Decision {
    code: DecisionCode,
    quorum_satisfied: bool,
    trust_keys_installed: bool,
    checkpoint_trusted: bool,
    chain_verified: bool,
    action_allowed: bool,
    production_action_allowed: bool,
}

const fn decision(code: DecisionCode, quorum_satisfied: bool) -> Decision {
    Decision {
        code,
        quorum_satisfied,
        trust_keys_installed: false,
        checkpoint_trusted: false,
        chain_verified: false,
        action_allowed: false,
        production_action_allowed: false,
    }
}

fn decide(input: &DecisionInput<'_>) -> Decision {
    if !input.binding_valid {
        return decision(DecisionCode::MalformedBinding, false);
    }
    if input
        .active_signer_ids
        .windows(2)
        .any(|pair| pair[0] == pair[1])
        || input.claims.len() > 2
    {
        return decision(DecisionCode::MalformedBinding, false);
    }
    let Some(active_epoch) = input.active_epoch else {
        return decision(DecisionCode::UnknownKeyEpoch, false);
    };
    if input.requested_epoch == 0 {
        return decision(DecisionCode::UnknownKeyEpoch, false);
    }
    if input.requested_epoch < active_epoch {
        return decision(DecisionCode::StaleKeyEpoch, false);
    }
    if input.requested_epoch > active_epoch {
        return decision(DecisionCode::UnknownKeyEpoch, false);
    }
    if input.expired {
        return decision(DecisionCode::ExpiredApproval, false);
    }
    if input
        .claims
        .iter()
        .any(|claim| !input.active_signer_ids.contains(&claim.signer_key_id))
    {
        return decision(DecisionCode::UnknownSigner, false);
    }
    if input.claims.iter().enumerate().any(|(index, claim)| {
        input.claims[index + 1..]
            .iter()
            .any(|other| other.signer_key_id == claim.signer_key_id)
    }) {
        return decision(DecisionCode::DuplicateSigner, false);
    }
    if input
        .claims
        .iter()
        .any(|claim| claim.outcome == FixtureSignatureOutcome::Malformed)
    {
        return decision(DecisionCode::MalformedSignature, false);
    }
    if input
        .claims
        .iter()
        .any(|claim| claim.outcome == FixtureSignatureOutcome::Invalid)
    {
        return decision(DecisionCode::InvalidSignature, false);
    }
    if input.claims.len() < 2 {
        return decision(DecisionCode::InsufficientQuorum, false);
    }
    decision(DecisionCode::QuorumSatisfiedNonAuthoritative, true)
}

fn fixture() -> DecisionInput<'static> {
    DecisionInput {
        binding_valid: true,
        requested_epoch: 4,
        active_epoch: Some(4),
        expired: false,
        active_signer_ids: ["signer_alpha", "signer_bravo", "signer_charlie"],
        claims: vec![
            Claim {
                signer_key_id: "signer_alpha",
                outcome: FixtureSignatureOutcome::Valid,
            },
            Claim {
                signer_key_id: "signer_bravo",
                outcome: FixtureSignatureOutcome::Valid,
            },
        ],
    }
}

#[test]
fn freezes_complete_ordered_decision_matrix() {
    let cases = [
        (DecisionCode::MalformedBinding, {
            let mut value = fixture();
            value.binding_valid = false;
            value
        }),
        (DecisionCode::UnknownKeyEpoch, {
            let mut value = fixture();
            value.active_epoch = None;
            value
        }),
        (DecisionCode::StaleKeyEpoch, {
            let mut value = fixture();
            value.requested_epoch = 3;
            value
        }),
        (DecisionCode::ExpiredApproval, {
            let mut value = fixture();
            value.expired = true;
            value
        }),
        (DecisionCode::UnknownSigner, {
            let mut value = fixture();
            value.claims[1].signer_key_id = "signer_unknown";
            value
        }),
        (DecisionCode::DuplicateSigner, {
            let mut value = fixture();
            value.claims[1].signer_key_id = "signer_alpha";
            value
        }),
        (DecisionCode::MalformedSignature, {
            let mut value = fixture();
            value.claims[1].outcome = FixtureSignatureOutcome::Malformed;
            value
        }),
        (DecisionCode::InvalidSignature, {
            let mut value = fixture();
            value.claims[1].outcome = FixtureSignatureOutcome::Invalid;
            value
        }),
        (DecisionCode::InsufficientQuorum, {
            let mut value = fixture();
            value.claims.pop();
            value
        }),
        (DecisionCode::QuorumSatisfiedNonAuthoritative, fixture()),
    ];

    for (expected, input) in cases {
        assert_eq!(decide(&input).code, expected);
    }
}

#[test]
fn future_and_zero_epochs_are_unknown_not_accepted() {
    for requested_epoch in [0, 5] {
        let mut input = fixture();
        input.requested_epoch = requested_epoch;
        assert_eq!(decide(&input).code, DecisionCode::UnknownKeyEpoch);
    }
}

#[test]
fn exact_two_claims_are_required_and_active_slots_must_be_distinct() {
    let mut too_many_claims = fixture();
    too_many_claims.claims.push(Claim {
        signer_key_id: "signer_charlie",
        outcome: FixtureSignatureOutcome::Valid,
    });
    assert_eq!(
        decide(&too_many_claims).code,
        DecisionCode::MalformedBinding
    );

    let mut duplicate_active_slot = fixture();
    duplicate_active_slot.active_signer_ids = ["signer_alpha", "signer_alpha", "signer_charlie"];
    assert_eq!(
        decide(&duplicate_active_slot).code,
        DecisionCode::MalformedBinding
    );
}

#[test]
fn failure_precedence_is_deterministic() {
    let mut input = fixture();
    input.binding_valid = false;
    input.active_epoch = None;
    input.expired = true;
    input.claims[0].outcome = FixtureSignatureOutcome::Invalid;
    assert_eq!(decide(&input).code, DecisionCode::MalformedBinding);

    let mut signer_precedence = fixture();
    signer_precedence.claims[0].signer_key_id = "signer_unknown";
    signer_precedence.claims[1].outcome = FixtureSignatureOutcome::Malformed;
    assert_eq!(decide(&signer_precedence).code, DecisionCode::UnknownSigner);
}

#[test]
fn every_outcome_is_non_authoritative() {
    let mut inputs = vec![fixture()];
    let mut invalid = fixture();
    invalid.claims[0].outcome = FixtureSignatureOutcome::Invalid;
    inputs.push(invalid);
    let mut malformed = fixture();
    malformed.binding_valid = false;
    inputs.push(malformed);

    for input in inputs {
        let result = decide(&input);
        assert!(!result.trust_keys_installed);
        assert!(!result.checkpoint_trusted);
        assert!(!result.chain_verified);
        assert!(!result.action_allowed);
        assert!(!result.production_action_allowed);
    }
    assert!(decide(&fixture()).quorum_satisfied);
}
