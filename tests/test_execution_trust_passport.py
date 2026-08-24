from copy import deepcopy

from relay.core.execution_trust_passport import passport_head, verify_passport


D = "a" * 64


def _passport():
    value = {
        "schema": "obsidian-execution-trust-passport.v1",
        "passport_id": {"action_type": "BUY", "intent_id": "intent-1", "intent_sha256": D, "created_at_epoch_ms": 1000},
        "action_intent": {"immutable_parameters_sha256": "b" * 64, "idempotency_key_sha256": D, "actor_subject_sha256": D},
        "service_lane": "PRIVATE_EXCHANGE",
        "identity_custody": {"identity_authority": "NONE", "custody_owner": "USER", "executor": "OBSIDIAN_EXCHANGE", "permission_snapshot_sha256": D},
        "quote_or_preview": {"market_or_transaction_snapshot_sha256": D, "fees_sha256": D, "expires_at_epoch_ms": 2000},
        "user_consent": {"display_sha256": D, "consent_sha256": D, "consented_parameters_sha256": "b" * 64, "consented_at_epoch_ms": 1500},
        "policy_decision": {"hard_policy_sha256": D, "hard_decision": "ALLOW", "advisory_evidence_sha256": D, "advisory_decision": "ALLOW", "effective_decision": "ALLOW", "decision_reason_code": "POLICY_ALLOW"},
        "execution_attempt": {"attempt_id": "attempt-1", "attempt_parameters_sha256": "b" * 64, "submitted_at_epoch_ms": 1600, "provider_evidence_sha256": D, "outcome": "CONFIRMED"},
        "settlement_or_reconciliation": {"observed_evidence_sha256": D, "reconciliation_policy_sha256": D, "final_state": "RECONCILED", "finalized_at_epoch_ms": 1700},
        "evidence_chain": {"previous_passport_event_sha256": D, "passport_head_sha256": "0" * 64, "independent_checkpoint_sha256": D},
    }
    value["evidence_chain"]["passport_head_sha256"] = passport_head(value)
    return value


def test_valid_passport_is_verified_but_non_authoritative():
    result = verify_passport(_passport())
    assert result.valid is True
    assert result.code == "VERIFIED_NON_AUTHORITATIVE"
    assert result.action_authority == "NONE"


def test_advisory_cannot_weaken_hard_policy():
    value = _passport()
    value["policy_decision"].update(hard_decision="FREEZE", advisory_decision="ALLOW", effective_decision="ALLOW")
    value["evidence_chain"]["passport_head_sha256"] = passport_head(value)
    assert verify_passport(value).code == "POLICY_WEAKENED"


def test_consent_and_execution_must_match_immutable_parameters():
    for section, field in [("user_consent", "consented_parameters_sha256"), ("execution_attempt", "attempt_parameters_sha256")]:
        value = _passport()
        value[section][field] = "c" * 64
        value["evidence_chain"]["passport_head_sha256"] = passport_head(value)
        assert verify_passport(value).code == "PARAMETER_DRIFT"


def test_quote_consent_submit_and_finalization_order_is_enforced():
    value = _passport()
    value["execution_attempt"]["submitted_at_epoch_ms"] = 1400
    value["evidence_chain"]["passport_head_sha256"] = passport_head(value)
    assert verify_passport(value).code == "TIME_ORDER"


def test_uncertain_execution_must_finish_in_review():
    value = _passport()
    value["execution_attempt"]["outcome"] = "UNKNOWN_REVIEW"
    value["settlement_or_reconciliation"]["final_state"] = "RECONCILED"
    value["evidence_chain"]["passport_head_sha256"] = passport_head(value)
    assert verify_passport(value).code == "UNCERTAIN_NOT_REVIEW"


def test_non_allow_policy_cannot_coexist_with_execution():
    value = _passport()
    value["policy_decision"].update(advisory_decision="HOLD", effective_decision="HOLD")
    value["evidence_chain"]["passport_head_sha256"] = passport_head(value)
    assert verify_passport(value).code == "POLICY_EXECUTION_CONFLICT"

    value["execution_attempt"]["outcome"] = "NOT_SUBMITTED"
    value["settlement_or_reconciliation"]["final_state"] = "NOT_FINAL"
    value["evidence_chain"]["passport_head_sha256"] = passport_head(value)
    assert verify_passport(value).valid is True


def test_any_bound_section_mutation_breaks_hash_chain():
    value = _passport()
    value["identity_custody"]["executor"] = "ATTACKER"
    assert verify_passport(value).code == "HASH_CHAIN"


def test_unknown_top_level_or_section_field_fails_closed():
    top = _passport()
    top["execute"] = True
    assert verify_passport(top).code == "CLOSED_SCHEMA"
    nested = _passport()
    nested["policy_decision"]["override"] = True
    assert verify_passport(nested).code == "SECTION_POLICY_DECISION"


def test_final_state_semantics_are_consistent():
    rejected = _passport()
    rejected["execution_attempt"]["outcome"] = "REJECTED"
    rejected["settlement_or_reconciliation"]["final_state"] = "RECONCILED"
    rejected["evidence_chain"]["passport_head_sha256"] = passport_head(rejected)
    assert verify_passport(rejected).code == "REJECTION_DRIFT"


def test_hash_is_deterministic_for_exact_content():
    first = _passport()
    second = deepcopy(first)
    assert passport_head(first) == passport_head(second)
