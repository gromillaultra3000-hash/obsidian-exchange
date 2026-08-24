//! Test-only ordered decision contract for future minimal DSSE verification.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum SignatureOutcome {
    Valid,
    Invalid,
}

#[derive(Clone, Copy, Debug)]
#[allow(clippy::struct_excessive_bools, reason = "ordered symbolic gates")]
struct Input {
    envelope_within_limits: bool,
    envelope_json_strict: bool,
    payload_type_exact: bool,
    base64_canonical: bool,
    signature_count: u8,
    signature_length: usize,
    root_epoch_known: bool,
    root_revoked: bool,
    signature_outcome: SignatureOutcome,
    verified_payload_json_strict: bool,
    statement_type_exact: bool,
    predicate_type_exact: bool,
    subject_exact: bool,
    builder_policy_exact: bool,
    external_parameters_exact: bool,
    dependencies_exact: bool,
    rebuild_digest_exact: bool,
    freshness_valid: bool,
    evidence_replayed: bool,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Code {
    EnvelopeLimitExceeded,
    MalformedEnvelope,
    WrongPayloadType,
    NonCanonicalBase64,
    SignatureCardinality,
    MalformedSignature,
    UnknownRootEpoch,
    RevokedRoot,
    InvalidSignature,
    MalformedVerifiedPayload,
    WrongStatementType,
    WrongPredicateType,
    SubjectMismatch,
    BuilderPolicyMismatch,
    UnknownExternalParameter,
    DependencyMismatch,
    RebuildMismatch,
    StaleEvidence,
    EvidenceReplay,
    VerifiedNonAuthoritative,
}

#[derive(Debug)]
#[allow(clippy::struct_excessive_bools, reason = "explicit verification gates")]
struct Decision {
    code: Code,
    pae_constructed_from_exact_bytes: bool,
    signature_verified: bool,
    verified_payload_parsed_once: bool,
    builder_authenticated: bool,
    acceptance_allowed: bool,
    production_action_allowed: bool,
}

const fn decision(code: Code, signature_verified: bool, payload_parsed: bool) -> Decision {
    Decision {
        code,
        pae_constructed_from_exact_bytes: signature_verified,
        signature_verified,
        verified_payload_parsed_once: payload_parsed,
        builder_authenticated: false,
        acceptance_allowed: false,
        production_action_allowed: false,
    }
}

fn decide(input: Input) -> Decision {
    if !input.envelope_within_limits {
        return decision(Code::EnvelopeLimitExceeded, false, false);
    }
    if !input.envelope_json_strict {
        return decision(Code::MalformedEnvelope, false, false);
    }
    if !input.payload_type_exact {
        return decision(Code::WrongPayloadType, false, false);
    }
    if !input.base64_canonical {
        return decision(Code::NonCanonicalBase64, false, false);
    }
    if input.signature_count != 1 {
        return decision(Code::SignatureCardinality, false, false);
    }
    if input.signature_length != 64 {
        return decision(Code::MalformedSignature, false, false);
    }
    if !input.root_epoch_known {
        return decision(Code::UnknownRootEpoch, false, false);
    }
    if input.root_revoked {
        return decision(Code::RevokedRoot, false, false);
    }
    if input.signature_outcome == SignatureOutcome::Invalid {
        return decision(Code::InvalidSignature, false, false);
    }
    if !input.verified_payload_json_strict {
        return decision(Code::MalformedVerifiedPayload, true, false);
    }
    if !input.statement_type_exact {
        return decision(Code::WrongStatementType, true, true);
    }
    if !input.predicate_type_exact {
        return decision(Code::WrongPredicateType, true, true);
    }
    if !input.subject_exact {
        return decision(Code::SubjectMismatch, true, true);
    }
    if !input.builder_policy_exact {
        return decision(Code::BuilderPolicyMismatch, true, true);
    }
    if !input.external_parameters_exact {
        return decision(Code::UnknownExternalParameter, true, true);
    }
    if !input.dependencies_exact {
        return decision(Code::DependencyMismatch, true, true);
    }
    if !input.rebuild_digest_exact {
        return decision(Code::RebuildMismatch, true, true);
    }
    if !input.freshness_valid {
        return decision(Code::StaleEvidence, true, true);
    }
    if input.evidence_replayed {
        return decision(Code::EvidenceReplay, true, true);
    }
    decision(Code::VerifiedNonAuthoritative, true, true)
}

const fn fixture() -> Input {
    Input {
        envelope_within_limits: true,
        envelope_json_strict: true,
        payload_type_exact: true,
        base64_canonical: true,
        signature_count: 1,
        signature_length: 64,
        root_epoch_known: true,
        root_revoked: false,
        signature_outcome: SignatureOutcome::Valid,
        verified_payload_json_strict: true,
        statement_type_exact: true,
        predicate_type_exact: true,
        subject_exact: true,
        builder_policy_exact: true,
        external_parameters_exact: true,
        dependencies_exact: true,
        rebuild_digest_exact: true,
        freshness_valid: true,
        evidence_replayed: false,
    }
}

#[test]
#[allow(clippy::too_many_lines, reason = "complete ordered decision matrix")]
fn freezes_ordered_fail_closed_matrix() {
    let cases = [
        (Code::EnvelopeLimitExceeded, {
            let mut x = fixture();
            x.envelope_within_limits = false;
            x
        }),
        (Code::MalformedEnvelope, {
            let mut x = fixture();
            x.envelope_json_strict = false;
            x
        }),
        (Code::WrongPayloadType, {
            let mut x = fixture();
            x.payload_type_exact = false;
            x
        }),
        (Code::NonCanonicalBase64, {
            let mut x = fixture();
            x.base64_canonical = false;
            x
        }),
        (Code::SignatureCardinality, {
            let mut x = fixture();
            x.signature_count = 2;
            x
        }),
        (Code::MalformedSignature, {
            let mut x = fixture();
            x.signature_length = 63;
            x
        }),
        (Code::UnknownRootEpoch, {
            let mut x = fixture();
            x.root_epoch_known = false;
            x
        }),
        (Code::RevokedRoot, {
            let mut x = fixture();
            x.root_revoked = true;
            x
        }),
        (Code::InvalidSignature, {
            let mut x = fixture();
            x.signature_outcome = SignatureOutcome::Invalid;
            x
        }),
        (Code::MalformedVerifiedPayload, {
            let mut x = fixture();
            x.verified_payload_json_strict = false;
            x
        }),
        (Code::WrongStatementType, {
            let mut x = fixture();
            x.statement_type_exact = false;
            x
        }),
        (Code::WrongPredicateType, {
            let mut x = fixture();
            x.predicate_type_exact = false;
            x
        }),
        (Code::SubjectMismatch, {
            let mut x = fixture();
            x.subject_exact = false;
            x
        }),
        (Code::BuilderPolicyMismatch, {
            let mut x = fixture();
            x.builder_policy_exact = false;
            x
        }),
        (Code::UnknownExternalParameter, {
            let mut x = fixture();
            x.external_parameters_exact = false;
            x
        }),
        (Code::DependencyMismatch, {
            let mut x = fixture();
            x.dependencies_exact = false;
            x
        }),
        (Code::RebuildMismatch, {
            let mut x = fixture();
            x.rebuild_digest_exact = false;
            x
        }),
        (Code::StaleEvidence, {
            let mut x = fixture();
            x.freshness_valid = false;
            x
        }),
        (Code::EvidenceReplay, {
            let mut x = fixture();
            x.evidence_replayed = true;
            x
        }),
        (Code::VerifiedNonAuthoritative, fixture()),
    ];
    for (expected, input) in cases {
        assert_eq!(decide(input).code, expected);
    }
}

#[test]
fn payload_is_never_parsed_before_signature_success() {
    let mut invalid = fixture();
    invalid.signature_outcome = SignatureOutcome::Invalid;
    invalid.verified_payload_json_strict = false;
    let rejected = decide(invalid);
    assert_eq!(rejected.code, Code::InvalidSignature);
    assert!(!rejected.pae_constructed_from_exact_bytes);
    assert!(!rejected.signature_verified);
    assert!(!rejected.verified_payload_parsed_once);

    let mut signed_but_malformed = fixture();
    signed_but_malformed.verified_payload_json_strict = false;
    let parsed = decide(signed_but_malformed);
    assert_eq!(parsed.code, Code::MalformedVerifiedPayload);
    assert!(parsed.pae_constructed_from_exact_bytes);
    assert!(parsed.signature_verified);
    assert!(!parsed.verified_payload_parsed_once);
}

#[test]
fn invalid_signature_short_circuits_all_later_policy() {
    let rejected = decide(Input {
        signature_outcome: SignatureOutcome::Invalid,
        verified_payload_json_strict: false,
        statement_type_exact: false,
        predicate_type_exact: false,
        subject_exact: false,
        builder_policy_exact: false,
        external_parameters_exact: false,
        dependencies_exact: false,
        rebuild_digest_exact: false,
        freshness_valid: false,
        evidence_replayed: true,
        ..fixture()
    });
    assert_eq!(rejected.code, Code::InvalidSignature);
    assert!(!rejected.verified_payload_parsed_once);
    assert!(!rejected.acceptance_allowed);
    assert!(!rejected.production_action_allowed);
}

#[test]
fn every_decision_remains_non_authoritative() {
    let result = decide(fixture());
    assert_eq!(result.code, Code::VerifiedNonAuthoritative);
    assert!(result.signature_verified);
    assert!(result.verified_payload_parsed_once);
    assert!(!result.builder_authenticated);
    assert!(!result.acceptance_allowed);
    assert!(!result.production_action_allowed);
}
