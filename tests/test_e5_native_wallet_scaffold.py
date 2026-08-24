import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WALLET = ROOT / "native-wallet"


def test_toolchain_workspace_and_uniffi_are_exactly_pinned():
    assert 'channel = "1.97.1"' in (WALLET / "rust-toolchain.toml").read_text()
    workspace = (WALLET / "Cargo.toml").read_text()
    assert 'rust-version = "1.97.1"' in workspace
    assert 'unsafe_code = "forbid"' in workspace
    ffi = (WALLET / "crates/wallet-ffi/Cargo.toml").read_text()
    assert 'uniffi = "=0.32.0"' in ffi
    lock = (WALLET / "Cargo.lock").read_text()
    assert 'name = "uniffi"\nversion = "0.32.0"' in lock


def test_core_uses_pinned_parser_and_remains_signet_only_and_non_signing():
    manifest = (WALLET / "crates/wallet-core/Cargo.toml").read_text()
    assert 'bitcoin = { version = "=0.32.102", default-features = false, features = ["std"] }' in manifest
    lock = (WALLET / "Cargo.lock").read_text()
    assert 'name = "bitcoin"\nversion = "0.32.102"' in lock
    source = (WALLET / "crates/wallet-core/src/lib.rs").read_text()
    assert "#![forbid(unsafe_code)]" in source
    assert "BitcoinSignet" in source
    assert "BITCOIN_MAINNET" not in source
    assert "require_network(BitcoinNetwork::Signet)" in source
    assert "CHECKSUM_NETWORK_AND_SCRIPT_VALIDATED_NOT_SIGNABLE" in source
    assert "script_pubkey_hex" in source
    assert "checked_add(request.amount_sats)" in source
    assert "let fee_sats = total_input_sats - total_output_sats" in source
    assert "NonCanonicalOutputs" in source
    assert "NonCanonicalInputs" in source
    assert "LockTime::from_consensus(lock_time)" in source
    assert "sha256::Hash::hash(&serialize(&transaction))" in source
    assert "script_sig: ScriptBuf::new()" in source
    assert "witness: Witness::new()" in source
    assert "native-signet-utxo-evidence.v1" in source
    assert "BITCOIN_CORE_SIGNET_RPC_SNAPSHOT_V1" in source
    assert "TX_INCLUSION_VERIFIED_CHAIN_AND_UTXO_STATE_NOT_VERIFIED" in source
    assert "extract_matches(&mut matched_txids" in source
    assert "proof.header.block_hash() != block_hash" in source
    assert "transaction_inclusion_verified: true" in source
    assert "UNREVIEWED_EXTERNAL_SIGNET_CHECKPOINT_V1" in source
    assert "LINKED_TO_UNREVIEWED_CHECKPOINT_NOT_CONSENSUS_VERIFIED" in source
    assert "checkpoint_trusted: false" in source
    assert "native-signet-checkpoint-review.v1" in source
    assert "independent_review_claims_bound: true" in source
    assert "HEADER_LINKAGE_ONLY_NO_SIGNET_CHALLENGE_OR_DIFFICULTY" in source
    assert "native-signet-checkpoint-approval-proposal.v1" in source
    assert "OFFLINE_2_OF_3_SIGNATURES_NOT_VERIFIED" in source
    assert "approval_proposal_content_bound: true" in source
    assert "approval_signatures_verified: false" in source
    assert "native-checkpoint-trust-key-ceremony.v1" in source
    assert "trust_key_ceremony_content_bound: true" in source
    assert "trust_keys_installed: false" in source
    assert "trust_key_algorithm_selected: false" in source
    assert "native-checkpoint-key-rotation-proposal.v1" in source
    assert "native-checkpoint-key-revocation-proposal.v1" in source
    assert "native-checkpoint-key-lifecycle-review.v1" in source
    assert "execution_allowed: false" in source
    ffi_source = (WALLET / "crates/wallet-ffi/src/lib.rs").read_text()
    assert "review_key_lifecycle_draft" in ffi_source
    assert "native-checkpoint-signature-algorithm-selection.v1" in source
    assert "BIP340_SECP256K1_XONLY_SHA256" in source
    assert "OBSIDIAN_CHECKPOINT_APPROVAL_V1" in source
    assert 'rust_secp256k1_version: "0.29.1"' in source
    assert "official_test_vectors_required: true" in source
    assert "verifier_implemented: false" in source
    assert "verifier_enabled: false" in source
    assert "signing_available: false" in source
    assert "checkpoint_signature_algorithm_selection_draft" in ffi_source
    assert "chain_verified: false" in source
    assert "signing_allowed: false" in source
    assert "production_action_allowed: false" in source


def test_scaffold_contains_no_secret_signing_storage_or_network_api():
    sources = "\n".join(
        path.read_text().lower()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    for forbidden in (
        "mnemonic", "seed_phrase", "private_key", "secret_key",
        "sign_transaction", "broadcast_transaction", "bitcoin_mainnet", "reqwest",
        "tokio", "std::net", "std::fs", "file::open", "sql", "keychain",
        "androidkeystore", "secureenclave",
    ):
        assert forbidden not in sources


def test_official_bip340_fixture_is_byte_exact_and_test_only():
    fixture = WALLET / "tests/fixtures/bip340-test-vectors.csv"
    provenance = (WALLET / "tests/fixtures/BIP340-PROVENANCE.md").read_text()
    harness = (WALLET / "crates/wallet-core/tests/bip340_vectors.rs").read_text()

    assert hashlib.sha256(fixture.read_bytes()).hexdigest() == (
        "34c9d1d9c3a88d524bc80778540dc43f8306ec249a7485293063c376db851c2d"
    )
    assert "c38071c8c45a1fc50cecaac0d82d99e3bbd56911" in provenance
    assert "include_str!" in harness
    assert "verify_schnorr" in harness
    assert "sign_schnorr" not in harness


def test_checkpoint_domain_binding_contract_remains_test_only():
    harness = (
        WALLET / "crates/wallet-core/tests/checkpoint_domain_binding.rs"
    ).read_text()
    core = (WALLET / "crates/wallet-core/src/lib.rs").read_text()
    ffi = (WALLET / "crates/wallet-ffi/src/lib.rs").read_text()

    assert 'const DOMAIN: &str = "OBSIDIAN_CHECKPOINT_APPROVAL_V1"' in harness
    assert "tag_hash" in harness
    assert "to_be_bytes" in harness
    assert "verify_schnorr" not in harness
    assert "checkpoint_domain_binding" not in core
    assert "checkpoint_domain_binding" not in ffi
    assert "verifier_implemented: false" in core
    assert "verifier_enabled: false" in core


def test_checkpoint_verification_matrix_is_symbolic_and_test_only():
    harness = (
        WALLET / "crates/wallet-core/tests/checkpoint_verification_matrix.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )

    for outcome in (
        "MalformedBinding", "UnknownKeyEpoch", "StaleKeyEpoch",
        "ExpiredApproval", "UnknownSigner", "DuplicateSigner",
        "MalformedSignature", "InvalidSignature", "InsufficientQuorum",
        "QuorumSatisfiedNonAuthoritative",
    ):
        assert outcome in harness
    assert "FixtureSignatureOutcome" in harness
    assert "verify_schnorr" not in harness
    assert "public_key" not in harness
    assert "signature_bytes" not in harness
    assert "checkpoint_verification_matrix" not in sources


def test_checkpoint_keyset_evidence_is_non_authoritative_and_test_only():
    harness = (
        WALLET / "crates/wallet-core/tests/checkpoint_keyset_evidence.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )

    assert "OBSIDIAN_CHECKPOINT_KEY_COMMITMENT_V1" in harness
    assert "XOnlyPublicKey::from_slice" in harness
    assert "mapping_reviewers_verified: false" in harness
    assert "keys_installed: false" in harness
    assert "active_key_authority: false" in harness
    assert "verify_schnorr" not in harness
    assert "SecretKey" not in harness
    assert "checkpoint_keyset_evidence" not in sources


def test_checkpoint_keyset_review_acceptance_remains_claim_only():
    harness = (
        WALLET
        / "crates/wallet-core/tests/checkpoint_keyset_review_acceptance.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )

    assert "REVIEW_CLAIMS_BOUND_NON_AUTHORITATIVE" in harness
    assert "independent_security" in harness
    assert "reproducible_build" in harness
    assert "reviewers_authenticated: false" in harness
    assert "bundle_accepted: false" in harness
    assert "keys_installed: false" in harness
    assert "verify_schnorr" not in harness
    assert "SecretKey" not in harness
    assert "checkpoint_keyset_review_acceptance" not in sources


def test_checkpoint_reviewer_policy_is_structural_and_test_only():
    harness = (
        WALLET / "crates/wallet-core/tests/checkpoint_reviewer_policy.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    assert "MAX_LIFETIME_MS: u64 = 600_000" in harness
    assert "MAX_FUTURE_SKEW_MS: u64 = 1_000" in harness
    assert "revocation_epoch" in harness
    assert "consumed_evidence_ids" in harness
    assert "attestations_verified: false" in harness
    assert "reviewers_authenticated: false" in harness
    assert "SecretKey" not in harness
    assert "verify_schnorr" not in harness
    assert "checkpoint_reviewer_policy" not in sources


def test_checkpoint_attestation_selection_is_read_only_and_test_only():
    harness = (
        WALLET / "crates/wallet-core/tests/checkpoint_attestation_selection.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    assert "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV" in harness
    assert "INTOTO_V1_SLSA_PROVENANCE_V1_DSSE_1_0_2_ED25519" in harness
    assert "SUPPLEMENTAL_TRANSPARENCY_NOT_TRUST_ROOT" in harness
    assert "sdk_selected: false" in harness
    assert "credentials_installed: false" in harness
    assert "verifier_implemented: false" in harness
    assert "checkpoint_attestation_selection" not in sources


def test_selected_attestation_envelopes_are_structural_and_test_only():
    webauthn = (
        WALLET / "crates/wallet-core/tests/checkpoint_webauthn_envelope.rs"
    ).read_text()
    build = (
        WALLET
        / "crates/wallet-core/tests/checkpoint_build_attestation_envelope.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    assert 'client_data_type: "webauthn.get"' in webauthn
    assert "user_verified: true" in webauthn
    assert "backup_eligible: false" in webauthn
    assert "signature_verified: false" in webauthn
    assert 'dsse_payload_type: "application/vnd.in-toto+json"' in build
    assert 'predicate_type: "https://slsa.dev/provenance/v1"' in build
    assert "reproducible_build_verified: false" in build
    assert "signature_verified: false" in build
    assert "checkpoint_webauthn_envelope" not in sources
    assert "checkpoint_build_attestation_envelope" not in sources


def test_attestation_verifier_shortlist_is_pinned_but_inactive():
    harness = (
        WALLET
        / "crates/wallet-core/tests/checkpoint_attestation_verifier_shortlist.rs"
    ).read_text()
    manifests = "\n".join(
        [
            (WALLET / "Cargo.toml").read_text(),
            *[
                path.read_text()
                for path in sorted((WALLET / "crates").glob("*/Cargo.toml"))
            ],
        ]
    )
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    assert 'human_rp_crate: "webauthn-rs"' in harness
    assert 'automated_signature_crate: "ed25519-dalek"' in harness
    assert 'automated_schema_candidate: "in_toto_attestation"' in harness
    assert "official_webauthn_server_vectors_available: false" in harness
    assert "dependencies_installed: false" in harness
    assert "fixtures_vendored: false" in harness
    assert "parser_implemented: false" in harness
    assert "trust_roots_installed: false" in harness
    for dependency in ("webauthn-rs", "ed25519-dalek", "in_toto_attestation"):
        assert dependency not in manifests
    assert "checkpoint_attestation_verifier_shortlist" not in sources


def test_webauthn_server_corpus_policy_is_independent_and_inactive():
    harness = (
        WALLET / "crates/wallet-core/tests/checkpoint_webauthn_corpus_policy.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    assert "VALID_ES256_UV_COUNTER_ZERO" in harness
    assert "CLIENT_DATA_DUPLICATE_KEY" in harness
    assert "EVIDENCE_ID_REPLAY" in harness
    assert "independent_oracle_required: true" in harness
    assert "two_independent_reviewers_required: true" in harness
    assert "expectations_written_before_results: true" in harness
    assert "official_conformance_claimed: false" in harness
    assert "raw_fixtures_present: false" in harness
    assert "private_test_keys_present: false" in harness
    assert "verifier_implemented: false" in harness
    assert "checkpoint_webauthn_corpus_policy" not in sources


def test_attestation_manifest_schema_and_source_provenance_are_inert():
    schema = json.loads(
        (WALLET / "tests/fixtures/webauthn-corpus-manifest.schema.json").read_text()
    )
    provenance = json.loads(
        (WALLET / "tests/fixtures/attestation-source-provenance.json").read_text()
    )
    assert schema["additionalProperties"] is False
    required = set(schema["required"])
    assert {
        "corpus_sha256", "expectations_sealed_before_results", "reviewers",
        "implementation_results", "agreement", "official_conformance_claimed",
        "authentication_allowed", "production_action_allowed",
    } <= required
    assert schema["properties"]["cases"]["minItems"] == 24
    assert schema["properties"]["official_conformance_claimed"]["const"] is False
    assert schema["$defs"]["case"]["properties"]["contains_private_key"]["const"] is False
    sources = provenance["sources"]
    assert len(sources) == 5
    assert len({source["id"] for source in sources}) == len(sources)
    for source in sources:
        assert len(source["revision"]) == 40
        assert len(source["sha256"]) == 64
        assert source["url"].startswith("https://raw.githubusercontent.com/")
        assert source["revision"] in source["url"]
        assert source["vendored"] is False
    assert provenance["fixtures_vendored"] is True
    assert provenance["dependencies_installed"] is False
    assert provenance["verification_implemented"] is False
    assert provenance["production_action_allowed"] is False


def test_attestation_dependency_rehearsals_are_isolated_and_non_authoritative():
    root = WALLET / "rehearsals/attestation-dependencies"
    results = json.loads((root / "RESULTS.json").read_text())
    profiles = {profile["id"]: profile for profile in results["profiles"]}
    assert profiles["human-rp"]["registry_packages"] == 116
    assert profiles["human-rp"]["host_check"] == "BLOCKED_NATIVE_OPENSSL_DISCOVERY"
    assert profiles["automated-minimal"]["registry_packages"] == 36
    assert profiles["automated-minimal"]["host_check"] == "PASS"
    assert profiles["automated-with-schema"]["registry_packages"] == 83
    assert profiles["automated-with-schema"]["additional_packages_vs_minimal"] == 47
    for profile in profiles.values():
        assert profile["rustsec_findings"] == 0
        assert profile["missing_license_metadata"] == 0
        assert profile["selected_for_integration"] is False
        directory = root / profile["id"]
        assert "[workspace]" in (directory / "Cargo.toml").read_text()
        assert "VERIFIER_IMPLEMENTED: bool = false" in (
            directory / "src/lib.rs"
        ).read_text()
        assert hashlib.sha256((directory / "Cargo.lock").read_bytes()).hexdigest() == (
            profile["lock_sha256"]
        )
    native_workspace = (WALLET / "Cargo.toml").read_text()
    assert "rehearsals" not in native_workspace
    assert results["native_workspace_changed"] is False
    assert results["verifier_implemented"] is False
    assert results["trust_roots_installed"] is False
    assert results["production_action_allowed"] is False


def test_dsse_and_mobile_provider_matrices_remain_symbolic_and_test_only():
    dsse = (
        WALLET / "crates/wallet-core/tests/checkpoint_dsse_verifier_matrix.rs"
    ).read_text()
    mobile = (
        WALLET
        / "crates/wallet-core/tests/checkpoint_mobile_webauthn_provider_matrix.rs"
    ).read_text()
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    assert "VerifiedNonAuthoritative" in dsse
    assert "NonCanonicalBase64" in dsse
    assert "UnknownRootEpoch" in dsse
    assert "InvalidSignature" in dsse
    assert "MalformedVerifiedPayload" in dsse
    assert "payload_is_never_parsed_before_signature_success" in dsse
    assert "ed25519_dalek" not in dsse
    assert "signature_bytes" not in dsse
    assert 'provider: "webauthn-rs-0.5.5-openssl-sys"' in mobile
    assert "ios_device_locked_build: false" in mobile
    assert "android_device_locked_build: false" in mobile
    assert "ambient_host_discovery_absent: false" in mobile
    assert "webauthn_integration_allowed: false" in mobile
    assert "credentials_allowed: false" in mobile
    assert "checkpoint_dsse_verifier_matrix" not in sources
    assert "checkpoint_mobile_webauthn_provider_matrix" not in sources


def test_dsse_parser_limits_and_safe_reference_are_test_only():
    harness = (
        WALLET / "crates/wallet-core/tests/checkpoint_dsse_parser_limits.rs"
    ).read_text()
    fixture = json.loads(
        (WALLET / "tests/fixtures/dsse-pae-reference-v1.json").read_text()
    )
    sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    for limit in (
        "MAX_ENVELOPE_BYTES: usize = 262_144",
        "MAX_PAYLOAD_BYTES: usize = 196_608",
        "MAX_JSON_TOKENS: usize = 8_192",
        "MAX_DEPENDENCIES: usize = 256",
        "MAX_EXTERNAL_PARAMETERS: usize = 32",
    ):
        assert limit in harness
    assert "canonical_standard_base64" in harness
    assert 'b"DSSEv1 29 http://example.com/HelloWorld 11 hello world"' in harness
    assert "ed25519_dalek" not in harness
    assert "verify_strict" not in harness
    assert fixture["contains_signature"] is False
    assert fixture["contains_public_key"] is False
    assert fixture["contains_private_or_signing_key"] is False
    assert fixture["official_standalone_conformance_vector"] is False
    assert fixture["verification_implemented"] is False
    assert hashlib.sha256(
        (WALLET / "tests/fixtures/dsse-pae-reference-v1.json").read_bytes()
    ).hexdigest() == "8567d731d583aca2092db6ab8957d69e332542c6cd25f8a3133bb69d45867d82"
    assert "checkpoint_dsse_parser_limits" not in sources


def test_isolated_strict_parser_rehearsal_has_no_crypto_or_authority():
    root = WALLET / "rehearsals/attestation-dependencies"
    source = (root / "automated-minimal/src/lib.rs").read_text()
    results = json.loads((root / "RESULTS.json").read_text())
    profile = next(item for item in results["profiles"] if item["id"] == "automated-minimal")
    assert "#[serde(deny_unknown_fields)]" in source
    assert "duplicate_and_unknown_fields_fail_at_nested_depths" in source
    assert "parse_verified_payload" in source
    assert "let mut stack = [0_u8; MAX_PAYLOAD_JSON_DEPTH]" in source
    assert "lexical_preflight_does_not_panic_for_any_two_byte_input" in source
    assert "STANDARD.encode(&decoded) != envelope.payload" in source
    assert "decode_payload_exact" in source
    assert "construct_pae" in source
    assert "DSSEv1 " in source
    assert "validate_verified_statement" in source
    assert "SymbolicSignatureOutcome" in source
    assert "PassedByTestOnlyOracle" in source
    assert "valid_closed_uri" in source
    assert "valid_sha256" in source
    assert "decode_signature_exact" in source
    assert "ED25519_SIGNATURE_BYTES: usize = 64" in source
    assert "STANDARD.encode(&decoded) != signature.sig" in source
    assert "validate_external_root_snapshot" in source
    assert "external_root_gate_is_ordered_and_keyid_cannot_select_it" in source
    assert "The unauthenticated DSSE `keyid` hint is intentionally absent" in source
    assert "ed25519_dalek" not in source
    assert "VerifyingKey" not in source
    assert "verify_strict" not in source
    assert "VERIFIER_IMPLEMENTED: bool = false" in source
    assert profile["strict_parser_rehearsal"] is True
    assert profile["allocation_safe_lexical_preflight"] is True
    assert profile["canonical_payload_decoding"] is True
    assert profile["exact_pae_construction"] is True
    assert profile["closed_semantic_policy"] is True
    assert profile["signature_outcome"] == "TEST_ONLY_SYMBOLIC"
    assert profile["canonical_signature_decoding"] is True
    assert profile["external_root_epoch_gate"] == "SYMBOLIC_NO_KEY_BYTES"
    assert profile["keyid_selects_root"] is False
    assert profile["signature_decoding_implemented"] is True
    assert profile["signature_verification_implemented"] is False
    native_sources = "\n".join(
        path.read_text()
        for path in sorted((WALLET / "crates").glob("*/src/*.rs"))
    )
    assert "parse_verified_payload" not in native_sources
