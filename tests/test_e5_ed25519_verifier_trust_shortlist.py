import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
SHORTLIST_PATH = FIXTURES / "ed25519-corpus-review-verifier-trust-shortlist-v1.json"
THREAT_MODEL_PATH = FIXTURES / "ed25519-corpus-review-verifier-threat-model-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_result_authentication_options_preserve_distinct_residual_risks():
    contract = _load(SHORTLIST_PATH)
    options = {item["id"]: item for item in contract["result_authentication_options"]}
    assert set(options) == {
        "local_pinned_execution", "dsse_signed_result",
        "hardware_workload_quote", "sigstore_keyless_bundle",
    }
    assert "forge IPC" in " ".join(options["local_pinned_execution"]["residual_risks"])
    assert "not which binary executed" in " ".join(options["dsse_signed_result"]["residual_risks"])
    assert options["hardware_workload_quote"]["status"] == "DEFERRED_COMPLEXITY"
    assert options["sigstore_keyless_bundle"]["status"] == "SUPPLEMENTAL_ONLY"


def test_build_identity_never_collapses_provenance_reproducibility_and_execution():
    contract = _load(SHORTLIST_PATH)
    sources = {item["id"]: item for item in contract["build_identity_sources"]}
    assert "artifact executed" in sources["reproducible_binary_digest"]["does_not_prove"]
    assert "reproducibility" in sources["intoto_slsa_dsse_provenance"]["does_not_prove"]
    assert "source provenance" in sources["hardware_measurement"]["does_not_prove"]
    assert sources["package_or_container_digest"]["status"] == "INSUFFICIENT_ALONE"


def test_future_result_must_cross_bind_all_security_context():
    contract = _load(SHORTLIST_PATH)
    assert contract["mandatory_cross_bindings"] == [
        "review_request_sha256", "assertion_envelope_sha256", "challenge_sha256",
        "evidence_id", "credential_root_sha256", "revocation_epoch",
        "verifier_build_sha256", "verifier_policy_sha256",
        "result_issued_at_epoch_ms", "result_expires_at_epoch_ms", "caller_nonce_sha256",
    ]
    assert "two independently reproduced verifier binaries" in contract["selection_prerequisites"]


def test_shortlist_selects_nothing_and_grants_nothing():
    contract = _load(SHORTLIST_PATH)
    assert contract["selected_result_authentication"] is None
    assert contract["selected_build_identity_source"] is None
    for field in [
        "real_verifier_result_present", "real_assertion_present", "credential_enrolled",
        "reviewer_authenticated", "crypto_call_allowed", "runtime_integration_allowed",
    ]:
        assert contract[field] is False


def test_threat_model_covers_substitution_replay_parser_and_independence():
    model = _load(THREAT_MODEL_PATH)
    cases = {item["id"]: item for item in model["abuse_cases"]}
    assert set(cases) == {f"tm{number:02d}_{suffix}" for number, suffix in [
        (1, "result_shape_impersonation"), (2, "build_digest_substitution"),
        (3, "signed_wrong_binary"), (4, "provenance_only_acceptance"),
        (5, "replay_and_rollback"), (6, "parser_differential"),
        (7, "one_domain_controls_both_reviews"), (8, "host_or_workload_compromise"),
    ]}
    assert model["acceptance_decision"] == "BLOCKED"
    assert len(model["blockers"]) == 4
    assert all(item["residual_status"] != "CLOSED" for item in cases.values())


def test_no_trust_material_or_real_evidence_is_present():
    for path in [SHORTLIST_PATH, THREAT_MODEL_PATH]:
        text = path.read_text(encoding="utf-8")
        for forbidden in ["private_key", "secret_key", "BEGIN PRIVATE", "credential_public_key"]:
            assert forbidden not in text
