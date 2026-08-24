//! Read-only selection contract; no parser, credential or verification code.

#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit unavailable capability claims"
)]
struct Selection {
    human_profile: &'static str,
    automated_profile: &'static str,
    webauthn_level: u8,
    ctap_version: &'static str,
    human_algorithm: &'static str,
    in_toto_statement: &'static str,
    slsa_version: &'static str,
    slsa_predicate_type: &'static str,
    dsse_version: &'static str,
    automated_algorithm: &'static str,
    sigstore_role: &'static str,
    sdk_selected: bool,
    credential_vendor_selected: bool,
    credentials_installed: bool,
    trust_roots_installed: bool,
    verifier_implemented: bool,
    reviewer_authenticated: bool,
    production_action_allowed: bool,
}

const fn selection() -> Selection {
    Selection {
        human_profile: "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV",
        automated_profile: "INTOTO_V1_SLSA_PROVENANCE_V1_DSSE_1_0_2_ED25519",
        webauthn_level: 3,
        ctap_version: "2.2-ps-20250714",
        human_algorithm: "ES256",
        in_toto_statement: "https://in-toto.io/Statement/v1",
        slsa_version: "1.2",
        slsa_predicate_type: "https://slsa.dev/provenance/v1",
        dsse_version: "1.0.2",
        automated_algorithm: "Ed25519-RFC8032",
        sigstore_role: "SUPPLEMENTAL_TRANSPARENCY_NOT_TRUST_ROOT",
        sdk_selected: false,
        credential_vendor_selected: false,
        credentials_installed: false,
        trust_roots_installed: false,
        verifier_implemented: false,
        reviewer_authenticated: false,
        production_action_allowed: false,
    }
}

#[test]
fn freezes_distinct_human_and_automated_profiles() {
    let value = selection();
    assert_eq!(value.human_profile, "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV");
    assert_eq!(value.webauthn_level, 3);
    assert_eq!(value.ctap_version, "2.2-ps-20250714");
    assert_eq!(value.human_algorithm, "ES256");
    assert_eq!(
        value.automated_profile,
        "INTOTO_V1_SLSA_PROVENANCE_V1_DSSE_1_0_2_ED25519"
    );
    assert_eq!(value.in_toto_statement, "https://in-toto.io/Statement/v1");
    assert_eq!(value.slsa_version, "1.2");
    assert_eq!(value.slsa_predicate_type, "https://slsa.dev/provenance/v1");
    assert_eq!(value.dsse_version, "1.0.2");
    assert_eq!(value.automated_algorithm, "Ed25519-RFC8032");
    assert_eq!(
        value.sigstore_role,
        "SUPPLEMENTAL_TRANSPARENCY_NOT_TRUST_ROOT"
    );
}

#[test]
fn selection_grants_no_capability() {
    let value = selection();
    assert!(!value.sdk_selected);
    assert!(!value.credential_vendor_selected);
    assert!(!value.credentials_installed);
    assert!(!value.trust_roots_installed);
    assert!(!value.verifier_implemented);
    assert!(!value.reviewer_authenticated);
    assert!(!value.production_action_allowed);
}
