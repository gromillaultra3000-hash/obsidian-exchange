//! Test-only policy for a future implementation-neutral `WebAuthn` RP corpus.

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum Expected {
    AcceptNonAuthoritative,
    Reject,
}

#[derive(Clone, Copy, Debug)]
struct Case {
    id: &'static str,
    expected: Expected,
    single_semantic_dimension: bool,
}

const CASES: &[Case] = &[
    Case {
        id: "VALID_ES256_UV_COUNTER_ZERO",
        expected: Expected::AcceptNonAuthoritative,
        single_semantic_dimension: true,
    },
    Case {
        id: "VALID_ES256_UV_COUNTER_ADVANCED",
        expected: Expected::AcceptNonAuthoritative,
        single_semantic_dimension: true,
    },
    Case {
        id: "TYPE_NOT_GET",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "CHALLENGE_MISMATCH",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "ORIGIN_MISMATCH",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "CROSS_ORIGIN_TRUE",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "RP_ID_HASH_MISMATCH",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "CREDENTIAL_ID_UNKNOWN",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "USER_PRESENCE_FALSE",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "USER_VERIFICATION_FALSE",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "BACKUP_ELIGIBLE_TRUE",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "BACKUP_STATE_TRUE",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "RESERVED_FLAG_SET",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "AUTHENTICATOR_DATA_TRUNCATED",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "SIGNATURE_DER_MALFORMED",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "SIGNATURE_INVALID",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "CLIENT_DATA_INVALID_UTF8",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "CLIENT_DATA_DUPLICATE_KEY",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "ALGORITHM_NOT_ES256",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "COSE_KEY_WRONG_CURVE",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "ENROLLMENT_STALE",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "EVIDENCE_ID_REPLAY",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "EXTENSION_BYTES_INCONSISTENT",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
    Case {
        id: "TRAILING_BYTES",
        expected: Expected::Reject,
        single_semantic_dimension: true,
    },
];

#[derive(Debug)]
#[allow(clippy::struct_excessive_bools, reason = "explicit activation gates")]
struct CorpusStatus {
    expectations_written_before_results: bool,
    independent_oracle_required: bool,
    two_independent_reviewers_required: bool,
    deterministic_generation_required: bool,
    official_conformance_claimed: bool,
    raw_fixtures_present: bool,
    private_test_keys_present: bool,
    verifier_implemented: bool,
    corpus_approved: bool,
    authentication_allowed: bool,
    production_action_allowed: bool,
}

const fn status() -> CorpusStatus {
    CorpusStatus {
        expectations_written_before_results: true,
        independent_oracle_required: true,
        two_independent_reviewers_required: true,
        deterministic_generation_required: true,
        official_conformance_claimed: false,
        raw_fixtures_present: false,
        private_test_keys_present: false,
        verifier_implemented: false,
        corpus_approved: false,
        authentication_allowed: false,
        production_action_allowed: false,
    }
}

#[test]
fn matrix_has_unique_ids_and_fail_closed_coverage() {
    assert!(CASES.len() >= 24);
    for (index, case) in CASES.iter().enumerate() {
        assert!(case.single_semantic_dimension);
        assert!(!case.id.is_empty());
        assert!(!CASES[..index].iter().any(|prior| prior.id == case.id));
    }
    assert_eq!(
        CASES
            .iter()
            .filter(|case| case.expected == Expected::AcceptNonAuthoritative)
            .count(),
        2
    );
    assert!(
        CASES
            .iter()
            .filter(|case| case.expected == Expected::Reject)
            .count()
            >= 22
    );
}

#[test]
fn corpus_policy_is_independent_but_inactive() {
    let state = status();
    assert!(state.expectations_written_before_results);
    assert!(state.independent_oracle_required);
    assert!(state.two_independent_reviewers_required);
    assert!(state.deterministic_generation_required);
    assert!(!state.official_conformance_claimed);
    assert!(!state.raw_fixtures_present);
    assert!(!state.private_test_keys_present);
    assert!(!state.verifier_implemented);
    assert!(!state.corpus_approved);
    assert!(!state.authentication_allowed);
    assert!(!state.production_action_allowed);
}
