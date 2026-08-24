import hashlib
import json
import re
from copy import deepcopy
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
SCHEMA_PATH = FIXTURES / "ed25519-corpus-review-independence-owner-reviewer-handoff-v1.schema.json"

SCHEMA_ID = "native-wallet-ed25519-corpus-review-independence-owner-reviewer-handoff.v1"
MAX_LIFETIME_MS = 86_400_000
MAX_FUTURE_SKEW_MS = 1_000
HEX64 = re.compile(r"^[0-9a-f]{64}$")
IDENTIFIER = re.compile(r"^[a-z0-9][a-z0-9._:-]{7,127}$")
FIELDS = {
    "schema", "handoff_id", "decision_result_sha256", "context_handoff_sha256",
    "selection_scorecard_sha256", "owner_role", "owner_identity_id", "owner_trust_domain",
    "owner_decision", "owner_assertion_sha256", "reviewer_role", "reviewer_identity_id",
    "reviewer_trust_domain", "reviewer_decision", "reviewer_assertion_sha256",
    "subject_review_domain_id", "issued_at_epoch_ms", "expires_at_epoch_ms",
    "caller_nonce_sha256", "handoff_sha256", "selected_option", "owner_authenticated",
    "independent_reviewer_authenticated", "decision_accepted", "production_authorized",
    "selection_allowed", "crypto_call_allowed", "runtime_integration_allowed",
}
DECISIONS = {"ACCEPT", "DEFER", "REJECT"}


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _digest(value: object) -> bool:
    return isinstance(value, str) and HEX64.fullmatch(value) is not None


def _identifier(value: object) -> bool:
    return isinstance(value, str) and IDENTIFIER.fullmatch(value) is not None


def _canonical_digest(value: dict) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _handoff_is_structurally_valid(
    handoff: dict,
    *,
    expected_result_sha256: str,
    expected_context: dict[str, str],
    now_epoch_ms: int,
    consumed_handoff_ids: set[str],
    consumed_caller_nonces: set[str],
) -> bool:
    if set(handoff) != FIELDS:
        return False
    if handoff["schema"] != SCHEMA_ID or not _identifier(handoff["handoff_id"]):
        return False
    if handoff["owner_role"] != "ACCOUNTABLE_OWNER" or handoff["reviewer_role"] != "INDEPENDENT_REVIEWER":
        return False
    if not all(_identifier(handoff[field]) for field in [
        "owner_identity_id", "owner_trust_domain", "reviewer_identity_id",
        "reviewer_trust_domain", "subject_review_domain_id",
    ]):
        return False
    if handoff["owner_identity_id"] == handoff["reviewer_identity_id"]:
        return False
    if handoff["owner_trust_domain"] == handoff["reviewer_trust_domain"]:
        return False
    if handoff["owner_trust_domain"] == handoff["subject_review_domain_id"]:
        return False
    if handoff["reviewer_trust_domain"] == handoff["subject_review_domain_id"]:
        return False
    if handoff["owner_decision"] not in DECISIONS or handoff["reviewer_decision"] not in DECISIONS:
        return False
    if not _digest(handoff["decision_result_sha256"]):
        return False
    if handoff["decision_result_sha256"] != expected_result_sha256:
        return False
    if handoff["context_handoff_sha256"] != _canonical_digest(expected_context):
        return False
    if handoff["selection_scorecard_sha256"] != expected_context["selection_scorecard_sha256"]:
        return False
    if not _digest(handoff["owner_assertion_sha256"]) or not _digest(handoff["reviewer_assertion_sha256"]):
        return False
    if handoff["owner_assertion_sha256"] == handoff["reviewer_assertion_sha256"]:
        return False
    if handoff["selected_option"] is not None:
        return False
    if any(handoff[field] is not False for field in [
        "owner_authenticated", "independent_reviewer_authenticated", "decision_accepted",
        "production_authorized", "selection_allowed", "crypto_call_allowed",
        "runtime_integration_allowed",
    ]):
        return False
    if not all(
        isinstance(handoff[field], int) and not isinstance(handoff[field], bool) and handoff[field] >= 1
        for field in ["issued_at_epoch_ms", "expires_at_epoch_ms"]
    ):
        return False
    if handoff["issued_at_epoch_ms"] > now_epoch_ms + MAX_FUTURE_SKEW_MS:
        return False
    if handoff["expires_at_epoch_ms"] <= now_epoch_ms:
        return False
    if (
        handoff["expires_at_epoch_ms"] <= handoff["issued_at_epoch_ms"]
        or handoff["expires_at_epoch_ms"] - handoff["issued_at_epoch_ms"] > MAX_LIFETIME_MS
    ):
        return False
    if handoff["handoff_id"] in consumed_handoff_ids or handoff["caller_nonce_sha256"] in consumed_caller_nonces:
        return False
    unsigned = {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    return _digest(handoff["handoff_sha256"]) and handoff["handoff_sha256"] == _canonical_digest(unsigned)


def _handoff_is_consumable(handoff: dict, **kwargs: object) -> bool:
    if not _handoff_is_structurally_valid(handoff, **kwargs):
        return False
    return (
        handoff["owner_authenticated"] is True
        and handoff["independent_reviewer_authenticated"] is True
        and handoff["decision_accepted"] is True
        and handoff["production_authorized"] is True
        and handoff["selection_allowed"] is True
    )


def _synthetic_handoff(*, owner_decision: str = "DEFER", reviewer_decision: str = "DEFER") -> tuple[dict, dict, str]:
    context = {
        "selection_scorecard_sha256": "1" * 64,
        "independence_evidence_sha256": "2" * 64,
        "supporting_bundle_sha256": "3" * 64,
        "conflict_matrix_sha256": "4" * 64,
        "issuer_challenge_sha256": "5" * 64,
        "subject_review_domain_id": "review-domain-a",
    }
    result_sha256 = "6" * 64
    handoff = {
        "schema": SCHEMA_ID,
        "handoff_id": "owner-review-handoff-a",
        "decision_result_sha256": result_sha256,
        "context_handoff_sha256": _canonical_digest(context),
        "selection_scorecard_sha256": context["selection_scorecard_sha256"],
        "owner_role": "ACCOUNTABLE_OWNER",
        "owner_identity_id": "owner-id-a",
        "owner_trust_domain": "owner-domain-a",
        "owner_decision": owner_decision,
        "owner_assertion_sha256": "7" * 64,
        "reviewer_role": "INDEPENDENT_REVIEWER",
        "reviewer_identity_id": "reviewer-b",
        "reviewer_trust_domain": "reviewer-domain-b",
        "reviewer_decision": reviewer_decision,
        "reviewer_assertion_sha256": "8" * 64,
        "subject_review_domain_id": context["subject_review_domain_id"],
        "issued_at_epoch_ms": 10_000,
        "expires_at_epoch_ms": 10_000 + MAX_LIFETIME_MS,
        "caller_nonce_sha256": "9" * 64,
        "handoff_sha256": "0" * 64,
        "selected_option": None,
        "owner_authenticated": False,
        "independent_reviewer_authenticated": False,
        "decision_accepted": False,
        "production_authorized": False,
        "selection_allowed": False,
        "crypto_call_allowed": False,
        "runtime_integration_allowed": False,
    }
    handoff["handoff_sha256"] = _canonical_digest(
        {key: value for key, value in handoff.items() if key != "handoff_sha256"}
    )
    return handoff, context, result_sha256


def test_handoff_schema_is_closed_and_currently_inert():
    schema = _load(SCHEMA_PATH)
    assert schema["additionalProperties"] is False
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["properties"]["selected_option"] == {"const": None}
    assert schema["properties"]["owner_authenticated"] == {"const": False}
    assert schema["properties"]["independent_reviewer_authenticated"] == {"const": False}
    assert schema["production_authorized"] is False
    assert schema["selection_allowed"] is False
    assert schema["crypto_call_allowed"] is False
    assert schema["runtime_integration_allowed"] is False
    assert schema["structural_handoff_is_not_authenticated_acceptance"] is True


def test_handoff_binds_exact_result_context_and_separates_roles():
    handoff, context, result_sha256 = _synthetic_handoff()
    assert _handoff_is_structurally_valid(
        handoff,
        expected_result_sha256=result_sha256,
        expected_context=context,
        now_epoch_ms=10_000,
        consumed_handoff_ids=set(),
        consumed_caller_nonces=set(),
    )
    for field, value in [
        ("decision_result_sha256", "a" * 64),
        ("context_handoff_sha256", "b" * 64),
        ("selection_scorecard_sha256", "c" * 64),
        ("owner_identity_id", "reviewer-b"),
        ("owner_trust_domain", "reviewer-domain-b"),
        ("reviewer_trust_domain", "review-domain-a"),
        ("reviewer_assertion_sha256", "7" * 64),
        ("selected_option", "threshold_dsse_offline_roots"),
    ]:
        changed = deepcopy(handoff)
        changed[field] = value
        assert not _handoff_is_structurally_valid(
            changed,
            expected_result_sha256=result_sha256,
            expected_context=context,
            now_epoch_ms=10_000,
            consumed_handoff_ids=set(),
            consumed_caller_nonces=set(),
        )


def test_structural_handoff_never_becomes_consumable_without_real_authentication():
    handoff, context, result_sha256 = _synthetic_handoff(owner_decision="ACCEPT", reviewer_decision="ACCEPT")
    kwargs = {
        "expected_result_sha256": result_sha256,
        "expected_context": context,
        "now_epoch_ms": 10_000,
        "consumed_handoff_ids": set(),
        "consumed_caller_nonces": set(),
    }
    assert _handoff_is_structurally_valid(handoff, **kwargs)
    assert not _handoff_is_consumable(handoff, **kwargs)
    for field in [
        "owner_authenticated", "independent_reviewer_authenticated", "decision_accepted",
        "production_authorized", "selection_allowed",
    ]:
        changed = deepcopy(handoff)
        changed[field] = True
        assert not _handoff_is_structurally_valid(changed, **kwargs)


def test_handoff_rejects_replay_time_shape_and_digest_drift():
    handoff, context, result_sha256 = _synthetic_handoff()
    kwargs = {
        "expected_result_sha256": result_sha256,
        "expected_context": context,
        "now_epoch_ms": 10_000,
        "consumed_handoff_ids": set(),
        "consumed_caller_nonces": set(),
    }
    assert not _handoff_is_structurally_valid(
        handoff,
        **{**kwargs, "consumed_handoff_ids": {handoff["handoff_id"]}},
    )
    assert not _handoff_is_structurally_valid(
        handoff,
        **{**kwargs, "consumed_caller_nonces": {handoff["caller_nonce_sha256"]}},
    )
    mutations = []
    for field, value in [
        ("expires_at_epoch_ms", 10_000),
        ("issued_at_epoch_ms", 10_000 + MAX_FUTURE_SKEW_MS + 1),
        ("caller_nonce_sha256", "d" * 64),
        ("handoff_sha256", "e" * 64),
    ]:
        changed = deepcopy(handoff)
        changed[field] = value
        mutations.append(changed)
    too_long = deepcopy(handoff)
    too_long["expires_at_epoch_ms"] = too_long["issued_at_epoch_ms"] + MAX_LIFETIME_MS + 1
    mutations.append(too_long)
    extra = deepcopy(handoff)
    extra["extra"] = "closed-shape-drift"
    mutations.append(extra)
    missing = deepcopy(handoff)
    missing.pop("handoff_sha256")
    mutations.append(missing)
    for changed in mutations:
        assert not _handoff_is_structurally_valid(changed, **kwargs)


def test_handoff_decision_conflict_remains_evidence_only():
    handoff, context, result_sha256 = _synthetic_handoff(owner_decision="ACCEPT", reviewer_decision="DEFER")
    assert _handoff_is_structurally_valid(
        handoff,
        expected_result_sha256=result_sha256,
        expected_context=context,
        now_epoch_ms=10_000,
        consumed_handoff_ids=set(),
        consumed_caller_nonces=set(),
    )
    assert handoff["decision_accepted"] is False
    assert handoff["selected_option"] is None


def test_no_real_identity_key_or_assertion_is_present():
    text = SCHEMA_PATH.read_text(encoding="utf-8")
    for forbidden in ["private_key", "secret_key", "BEGIN PRIVATE", "credential_private_key"]:
        assert forbidden not in text
