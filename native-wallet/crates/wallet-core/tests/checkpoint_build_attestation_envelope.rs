//! Test-only structural in-toto/SLSA/DSSE build-attestation envelope.

#[derive(Clone)]
struct Envelope<'a> {
    schema: &'a str,
    dsse_payload_type: &'a str,
    statement_type: &'a str,
    predicate_type: &'a str,
    subject_name: &'a str,
    subject_sha256: &'a str,
    rebuild_sha256: &'a str,
    builder_id: &'a str,
    build_type: &'a str,
    source_uri: &'a str,
    source_revision: &'a str,
    dependencies: Vec<(&'a str, &'a str)>,
    external_parameters: Vec<(&'a str, &'a str)>,
    dsse_payload_sha256: &'a str,
    credential_root_sha256: &'a str,
    signature_sha256: &'a str,
}

#[derive(Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "explicit non-authority claims"
)]
struct Review {
    envelope_expectations_bound: bool,
    subject_matches_rebuild_claim: bool,
    dependencies_bound: bool,
    external_parameters_bound: bool,
    signature_verified: bool,
    builder_authenticated: bool,
    reproducible_build_verified: bool,
    acceptance_allowed: bool,
    production_action_allowed: bool,
}

fn digest(value: &str) -> bool {
    value.len() == 64
        && value
            .bytes()
            .all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
}

fn review(envelope: &Envelope<'_>, expected_rebuild_sha256: &str) -> Result<Review, String> {
    let expected_dependencies = [
        (
            "cargo-lock",
            "11f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        ),
        (
            "source-tree",
            "22f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        ),
        (
            "toolchain",
            "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        ),
    ];
    let expected_parameters = [("profile", "release"), ("target", "aarch64-apple-ios")];
    if envelope.schema != "native-checkpoint-build-attestation-envelope.v1"
        || envelope.dsse_payload_type != "application/vnd.in-toto+json"
        || envelope.statement_type != "https://in-toto.io/Statement/v1"
        || envelope.predicate_type != "https://slsa.dev/provenance/v1"
        || envelope.subject_name != "obsidian-wallet-core.a"
        || envelope.subject_sha256 != expected_rebuild_sha256
        || envelope.subject_sha256 != envelope.rebuild_sha256
        || envelope.builder_id != "https://build.obsidian.invalid/reproducible/v1"
        || envelope.build_type != "https://build.obsidian.invalid/native-wallet/v1"
        || envelope.source_uri != "git+https://example.invalid/obsidian/native-wallet"
        || envelope.source_revision != "0123456789abcdef0123456789abcdef01234567"
        || envelope.dependencies != expected_dependencies
        || envelope.external_parameters != expected_parameters
        || ![
            envelope.subject_sha256,
            envelope.rebuild_sha256,
            envelope.dsse_payload_sha256,
            envelope.credential_root_sha256,
            envelope.signature_sha256,
        ]
        .iter()
        .all(|value| digest(value))
    {
        return Err("build attestation envelope rejected".to_owned());
    }
    Ok(Review {
        envelope_expectations_bound: true,
        subject_matches_rebuild_claim: true,
        dependencies_bound: true,
        external_parameters_bound: true,
        signature_verified: false,
        builder_authenticated: false,
        reproducible_build_verified: false,
        acceptance_allowed: false,
        production_action_allowed: false,
    })
}

fn fixture() -> Envelope<'static> {
    Envelope {
        schema: "native-checkpoint-build-attestation-envelope.v1",
        dsse_payload_type: "application/vnd.in-toto+json",
        statement_type: "https://in-toto.io/Statement/v1",
        predicate_type: "https://slsa.dev/provenance/v1",
        subject_name: "obsidian-wallet-core.a",
        subject_sha256: "44f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        rebuild_sha256: "44f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        builder_id: "https://build.obsidian.invalid/reproducible/v1",
        build_type: "https://build.obsidian.invalid/native-wallet/v1",
        source_uri: "git+https://example.invalid/obsidian/native-wallet",
        source_revision: "0123456789abcdef0123456789abcdef01234567",
        dependencies: vec![
            (
                "cargo-lock",
                "11f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            ),
            (
                "source-tree",
                "22f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            ),
            (
                "toolchain",
                "33f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
            ),
        ],
        external_parameters: vec![("profile", "release"), ("target", "aarch64-apple-ios")],
        dsse_payload_sha256: "55f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        credential_root_sha256: "66f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
        signature_sha256: "77f0eeb89e2550c9f10770f87715e01285cb36ea975fd4770f645222815a5eac",
    }
}

#[test]
fn exact_build_envelope_remains_non_authoritative() -> Result<(), String> {
    let envelope = fixture();
    let result = review(&envelope, envelope.rebuild_sha256)?;
    assert!(result.envelope_expectations_bound);
    assert!(result.subject_matches_rebuild_claim);
    assert!(result.dependencies_bound);
    assert!(result.external_parameters_bound);
    assert!(!result.signature_verified);
    assert!(!result.builder_authenticated);
    assert!(!result.reproducible_build_verified);
    assert!(!result.acceptance_allowed);
    assert!(!result.production_action_allowed);
    Ok(())
}

#[test]
fn identity_source_subject_and_payload_drift_fail_closed() {
    let mut cases = Vec::new();
    let mut builder = fixture();
    builder.builder_id = "https://attacker.invalid/builder";
    cases.push(builder);
    let mut source = fixture();
    source.source_revision = "ffffffffffffffffffffffffffffffffffffffff";
    cases.push(source);
    let mut subject = fixture();
    subject.rebuild_sha256 = "8888888888888888888888888888888888888888888888888888888888888888";
    cases.push(subject);
    let mut payload_type = fixture();
    payload_type.dsse_payload_type = "application/json";
    cases.push(payload_type);
    for case in cases {
        assert!(review(&case, case.rebuild_sha256).is_err());
    }
    let envelope = fixture();
    assert!(
        review(
            &envelope,
            "8888888888888888888888888888888888888888888888888888888888888888"
        )
        .is_err()
    );
}

#[test]
fn dependency_and_external_parameter_matrices_are_exact() {
    let mut unknown_parameter = fixture();
    unknown_parameter
        .external_parameters
        .push(("feature", "unsafe"));
    assert!(review(&unknown_parameter, unknown_parameter.rebuild_sha256).is_err());
    let mut dependency_order = fixture();
    dependency_order.dependencies.swap(0, 1);
    assert!(review(&dependency_order, dependency_order.rebuild_sha256).is_err());
    let mut duplicate_dependency = fixture();
    duplicate_dependency.dependencies[2] = duplicate_dependency.dependencies[1];
    assert!(review(&duplicate_dependency, duplicate_dependency.rebuild_sha256).is_err());
}
