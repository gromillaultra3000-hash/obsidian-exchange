//! Test-only mobile crypto-provider acceptance matrix for future `WebAuthn`.

#[derive(Clone, Copy)]
#[allow(clippy::struct_excessive_bools, reason = "explicit provider gates")]
struct Candidate<'a> {
    provider: &'a str,
    ios_device_locked_build: bool,
    android_device_locked_build: bool,
    test_targets_locked_build: bool,
    ambient_host_discovery_absent: bool,
    fallback_provider_absent: bool,
    es256_corpus_passed: bool,
    reproducible_binaries: bool,
    measured_size_budget_passed: bool,
    security_update_path_reviewed: bool,
    rustsec_and_native_cve_clean: bool,
    vendored_openssl_default_absent: bool,
    dynamic_libraries_declared: bool,
    mobile_distribution_licenses_reviewed: bool,
    cross_platform_policy_identical: bool,
}

#[derive(Debug, Eq, PartialEq)]
#[allow(clippy::struct_excessive_bools, reason = "explicit authority gates")]
struct Review {
    provider_accepted: bool,
    webauthn_integration_allowed: bool,
    credentials_allowed: bool,
    reviewer_authentication_allowed: bool,
    production_action_allowed: bool,
}

const fn review(candidate: Candidate<'_>) -> Review {
    let provider_accepted = !candidate.provider.is_empty()
        && candidate.ios_device_locked_build
        && candidate.android_device_locked_build
        && candidate.test_targets_locked_build
        && candidate.ambient_host_discovery_absent
        && candidate.fallback_provider_absent
        && candidate.es256_corpus_passed
        && candidate.reproducible_binaries
        && candidate.measured_size_budget_passed
        && candidate.security_update_path_reviewed
        && candidate.rustsec_and_native_cve_clean
        && candidate.vendored_openssl_default_absent
        && candidate.dynamic_libraries_declared
        && candidate.mobile_distribution_licenses_reviewed
        && candidate.cross_platform_policy_identical;
    Review {
        provider_accepted,
        webauthn_integration_allowed: false,
        credentials_allowed: false,
        reviewer_authentication_allowed: false,
        production_action_allowed: false,
    }
}

const fn current_openssl_path() -> Candidate<'static> {
    Candidate {
        provider: "webauthn-rs-0.5.5-openssl-sys",
        ios_device_locked_build: false,
        android_device_locked_build: false,
        test_targets_locked_build: false,
        ambient_host_discovery_absent: false,
        fallback_provider_absent: true,
        es256_corpus_passed: false,
        reproducible_binaries: false,
        measured_size_budget_passed: false,
        security_update_path_reviewed: false,
        rustsec_and_native_cve_clean: false,
        vendored_openssl_default_absent: true,
        dynamic_libraries_declared: false,
        mobile_distribution_licenses_reviewed: false,
        cross_platform_policy_identical: false,
    }
}

#[test]
fn current_openssl_path_is_blocked() {
    let result = review(current_openssl_path());
    assert!(!result.provider_accepted);
    assert!(!result.webauthn_integration_allowed);
    assert!(!result.credentials_allowed);
    assert!(!result.reviewer_authentication_allowed);
    assert!(!result.production_action_allowed);
}

#[test]
fn structural_matrix_success_still_grants_no_capability() {
    let result = review(Candidate {
        provider: "synthetic-reviewed-provider",
        ios_device_locked_build: true,
        android_device_locked_build: true,
        test_targets_locked_build: true,
        ambient_host_discovery_absent: true,
        fallback_provider_absent: true,
        es256_corpus_passed: true,
        reproducible_binaries: true,
        measured_size_budget_passed: true,
        security_update_path_reviewed: true,
        rustsec_and_native_cve_clean: true,
        vendored_openssl_default_absent: true,
        dynamic_libraries_declared: true,
        mobile_distribution_licenses_reviewed: true,
        cross_platform_policy_identical: true,
    });
    assert!(result.provider_accepted);
    assert!(!result.webauthn_integration_allowed);
    assert!(!result.credentials_allowed);
    assert!(!result.reviewer_authentication_allowed);
    assert!(!result.production_action_allowed);
}
