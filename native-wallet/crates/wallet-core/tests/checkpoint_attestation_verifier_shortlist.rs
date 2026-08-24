//! Test-only record of the read-only attestation verifier shortlist.

#[derive(Debug)]
#[allow(clippy::struct_excessive_bools, reason = "explicit activation gates")]
struct Shortlist<'a> {
    human_rp_crate: &'a str,
    human_rp_version: &'a str,
    automated_schema_candidate: &'a str,
    automated_schema_version: &'a str,
    automated_signature_crate: &'a str,
    automated_signature_version: &'a str,
    dsse_revision: &'a str,
    intoto_revision: &'a str,
    slsa_revision: &'a str,
    official_webauthn_server_vectors_available: bool,
    dependencies_installed: bool,
    fixtures_vendored: bool,
    parser_implemented: bool,
    signature_verified: bool,
    trust_roots_installed: bool,
    acceptance_allowed: bool,
    production_action_allowed: bool,
}

const fn shortlist() -> Shortlist<'static> {
    Shortlist {
        human_rp_crate: "webauthn-rs",
        human_rp_version: "0.5.5",
        automated_schema_candidate: "in_toto_attestation",
        automated_schema_version: "0.1.0",
        automated_signature_crate: "ed25519-dalek",
        automated_signature_version: "3.0.0",
        dsse_revision: "440901313676fedd0e31f16125c302b0df81e006",
        intoto_revision: "df02077bf97218a8860a5c534eff1f1381f56984",
        slsa_revision: "19e4e2f005f871270c4f555fc47afecfb37f3efe",
        official_webauthn_server_vectors_available: false,
        dependencies_installed: false,
        fixtures_vendored: false,
        parser_implemented: false,
        signature_verified: false,
        trust_roots_installed: false,
        acceptance_allowed: false,
        production_action_allowed: false,
    }
}

#[test]
fn shortlist_is_pinned_but_completely_inactive() {
    let choice = shortlist();
    assert_eq!(choice.human_rp_crate, "webauthn-rs");
    assert_eq!(choice.human_rp_version, "0.5.5");
    assert_eq!(choice.automated_schema_candidate, "in_toto_attestation");
    assert_eq!(choice.automated_schema_version, "0.1.0");
    assert_eq!(choice.automated_signature_crate, "ed25519-dalek");
    assert_eq!(choice.automated_signature_version, "3.0.0");
    assert_eq!(choice.dsse_revision.len(), 40);
    assert_eq!(choice.intoto_revision.len(), 40);
    assert_eq!(choice.slsa_revision.len(), 40);
    assert!(!choice.official_webauthn_server_vectors_available);
    assert!(!choice.dependencies_installed);
    assert!(!choice.fixtures_vendored);
    assert!(!choice.parser_implemented);
    assert!(!choice.signature_verified);
    assert!(!choice.trust_roots_installed);
    assert!(!choice.acceptance_allowed);
    assert!(!choice.production_action_allowed);
}

#[test]
fn rejected_substitutes_are_not_selected() {
    let choice = shortlist();
    for rejected in ["passkey-rs", "sigstore", "in-toto", "custom-webauthn"] {
        assert_ne!(choice.human_rp_crate, rejected);
        assert_ne!(choice.automated_signature_crate, rejected);
    }
}
