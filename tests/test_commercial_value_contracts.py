import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
COMMERCIAL = ROOT / "contracts/commercial"


def _load(name: str) -> dict:
    return json.loads((COMMERCIAL / name).read_text(encoding="utf-8"))


def test_acquisition_scorecard_weights_sum_and_unknowns_do_not_create_value():
    scorecard = _load("acquisition-readiness-scorecard.v1.json")
    assert sum(item["weight"] for item in scorecard["categories"]) == 100
    assert scorecard["weights_sum"] == 100
    assert all(item["required_evidence"] for item in scorecard["categories"])
    assert scorecard["verified_score"] is None
    assert scorecard["score_publication_allowed"] is False
    assert scorecard["unsupported_valuation_claim_allowed"] is False


def test_scorecard_covers_finance_legal_traction_security_transfer_and_ip():
    ids = {item["id"] for item in _load("acquisition-readiness-scorecard.v1.json")["categories"]}
    assert ids == {
        "financial_quality", "legal_regulatory", "traction_market",
        "technology_security", "operations_transferability",
        "ip_defensibility", "transaction_readiness",
    }


def test_innovation_registry_forbids_unsupported_uniqueness():
    registry = _load("innovation-claims-registry.v1.json")
    assert registry["claim_policy"]["unique_label_allowed"] is False
    assert registry["claim_policy"]["patentability_claim_allowed"] is False
    assert registry["validated_moat_count"] == 0
    assert registry["legal_uniqueness_claim_allowed"] is False
    assert all(claim["missing_evidence"] for claim in registry["claims"])


def test_execution_passport_binds_full_action_without_authority():
    passport = _load("execution-trust-passport.v1.json")
    assert set(passport["required_sections"]) == set(passport["section_contracts"])
    assert passport["action_authority"] == "NONE"
    assert passport["may_trigger_execution"] is False
    assert passport["may_retry_execution"] is False
    assert passport["prototype_implemented"] is False
    assert passport["production_emission_enabled"] is False


def test_passport_has_identity_custody_consent_policy_execution_and_reconciliation():
    passport = _load("execution-trust-passport.v1.json")
    sections = passport["section_contracts"]
    assert {"identity_authority", "custody_owner", "executor"} <= set(sections["identity_custody"])
    assert "consent_sha256" in sections["user_consent"]
    assert "hard_policy_sha256" in sections["policy_decision"]
    assert "provider_evidence_sha256" in sections["execution_attempt"]
    assert "reconciliation_policy_sha256" in sections["settlement_or_reconciliation"]


def test_passport_privacy_excludes_secrets_identity_documents_and_free_text():
    rules = " ".join(_load("execution-trust-passport.v1.json")["privacy_rules"])
    for required in ["seed private key", "credential token", "raw identity document", "free text is forbidden"]:
        assert required in rules


def test_moat_claim_remains_unvalidated_until_market_and_legal_evidence():
    passport = _load("execution-trust-passport.v1.json")
    for field in ["buyer_value_validated", "prior_art_review_complete", "freedom_to_operate_review_complete"]:
        assert passport[field] is False


def test_financial_component_ledger_is_fail_closed_until_accounting_approval():
    ledger = _load("financial-component-ledger.v1.json")
    assert "crypto_acquisition_cost" in ledger["component_types"]
    assert "source_record_sha256" in ledger["required_entry_fields"]
    assert ledger["accounting_policy_gate"]["gross_vs_net_policy_approved"] is False
    assert ledger["may_publish_revenue"] is False
    assert ledger["may_publish_gross_margin"] is False
