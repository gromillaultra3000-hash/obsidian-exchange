import copy
import hashlib
import json
import sys
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.b64_064a_decision import (  # noqa: E402
    build_owner_envelope, build_reviewer_envelope, build_statement,
    verify_decision,
)

NOW = 1_800_000_000
INPUT = hashlib.sha256((ROOT / "docs/e0-3-bot-b5-3-064a-decision-input.v1.json").read_bytes()).hexdigest()
BUNDLE = "b" * 64
KEYRING = "c" * 64
REVIEW_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(1, 33)))
OWNER_KEY = Ed25519PrivateKey.from_private_bytes(bytes(range(33, 65)))
KEYS = {"review_key": REVIEW_KEY, "owner_key": OWNER_KEY}
REGISTRY = {
    "review_key": {"status": "ACTIVE", "role": "INDEPENDENT_REVIEWER",
                   "identityId": "reviewer_1", "trustDomain": "review_org",
                   "trustEnvironment": "SYNTHETIC_TEST_ONLY"},
    "owner_key": {"status": "ACTIVE", "role": "ACCOUNTABLE_OWNER",
                  "identityId": "owner_1", "trustDomain": "owner_org",
                  "trustEnvironment": "SYNTHETIC_TEST_ONLY"},
}


def signer(key_id, payload):
    return KEYS[key_id].sign(payload)


def verifier(key_id, signature, payload):
    KEYS[key_id].public_key().verify(signature, payload)


class Ledger:
    def __init__(self): self.used = set()
    def consume(self, review, owner, decision):
        values = {review, owner, ("decision", decision)}
        if self.used & values: return False
        self.used |= values
        return True


SOURCE_OBSERVED = NOW - 60
SOURCE_EXPIRES = SOURCE_OBSERVED + 86400


def bundle(*, source_bound=False):
    statement = build_statement(
        decision_input_sha256=INPUT, evidence_bundle_sha256=BUNDLE,
        issued_at_epoch=NOW, expires_at_epoch=NOW + 3600,
        nonce="AQEBAQEBAQEBAQEBAQEBAQ",
        source_observed_at_epoch=SOURCE_OBSERVED if source_bound else None,
        source_expires_at_epoch=SOURCE_EXPIRES if source_bound else None)
    review = build_reviewer_envelope(
        statement_sha256=statement["statementSha256"], key_id="review_key",
        identity_id="reviewer_1", trust_domain="review_org",
        keyring_sha256=KEYRING, issued_at_epoch=NOW,
        expires_at_epoch=NOW + 3600, nonce="AgICAgICAgICAgICAgICAg", sign=signer)
    owner = build_owner_envelope(
        review_envelope=review, statement_sha256=statement["statementSha256"],
        key_id="owner_key", identity_id="owner_1", trust_domain="owner_org",
        keyring_sha256=KEYRING, issued_at_epoch=NOW,
        expires_at_epoch=NOW + 3600, nonce="AwMDAwMDAwMDAwMDAwMDAw", sign=signer)
    return statement, review, owner


def check(statement=None, review=None, owner=None, *, ledger=None,
          trust="SYNTHETIC_TEST_ONLY", current=INPUT, registry=REGISTRY, now=NOW + 1,
          source_window=None):
    original = bundle(source_bound=source_window is not None)
    return verify_decision(
        statement=original[0] if statement is None else statement,
        reviewer=original[1] if review is None else review,
        owner=original[2] if owner is None else owner, registry=registry,
        expected_keyring_sha256=KEYRING, current_input_sha256=current,
        now_epoch=now, verify_signature=verifier,
        consume_pair=(ledger or Ledger()).consume, trust_environment=trust,
        expected_source_observed_at_epoch=(source_window or (None, None))[0],
        expected_source_expires_at_epoch=(source_window or (None, None))[1])


def test_two_valid_synthetic_signatures_prove_protocol_but_authorize_nothing():
    result = check()
    assert result["status"] == "SYNTHETIC_VALID"
    assert result["syntheticProtocolValid"] is True
    for field in ("authenticatedOwnerReviewerGo", "boundedEvidenceAccepted",
                  "packagePreparationEligible", "productionExpandAuthorized",
                  "cutoverAuthorized", "actionAllowed"):
        assert result[field] is False


def test_symbolic_production_registry_path_accepts_only_bounded_evidence():
    production_registry = copy.deepcopy(REGISTRY)
    for key in production_registry.values():
        key["trustEnvironment"] = "PRODUCTION_AUTHENTICATED"
    result = check(trust="PRODUCTION_AUTHENTICATED", registry=production_registry,
                   source_window=(SOURCE_OBSERVED, SOURCE_EXPIRES))
    assert result["boundedEvidenceAccepted"] is True
    assert result["packagePreparationEligible"] is True
    assert result["productionExpandAuthorized"] is False
    assert result["cutoverAuthorized"] is False and result["actionAllowed"] is False


def test_production_rejects_legacy_statement_even_with_authenticated_profiles():
    production_registry = copy.deepcopy(REGISTRY)
    for key in production_registry.values():
        key["trustEnvironment"] = "PRODUCTION_AUTHENTICATED"
    assert check(trust="PRODUCTION_AUTHENTICATED",
                 registry=production_registry)["status"] == "INVALID"


def test_source_window_is_exact_and_statement_cannot_outlive_it():
    statement, review, owner = bundle(source_bound=True)
    assert check(statement, review, owner,
                 source_window=(SOURCE_OBSERVED, SOURCE_EXPIRES))["syntheticProtocolValid"] is True
    assert check(statement, review, owner,
                 source_window=(SOURCE_OBSERVED + 1, SOURCE_EXPIRES))["status"] == "INVALID"
    changed = copy.deepcopy(statement)
    changed["sourceExpiresAtEpoch"] += 1
    assert check(changed, review, owner,
                 source_window=(SOURCE_OBSERVED, SOURCE_EXPIRES))["status"] == "INVALID"
    try:
        build_statement(decision_input_sha256=INPUT, evidence_bundle_sha256=BUNDLE,
            issued_at_epoch=NOW, expires_at_epoch=SOURCE_EXPIRES + 1,
            nonce="AQEBAQEBAQEBAQEBAQEBAQ",
            source_observed_at_epoch=SOURCE_OBSERVED,
            source_expires_at_epoch=SOURCE_EXPIRES)
    except ValueError as exc:
        assert str(exc) == "invalid_source_window"
    else:
        raise AssertionError("statement outlived its source window")
    for invalid_source_expiry in (SOURCE_EXPIRES - 1, SOURCE_EXPIRES + 1,
                                  SOURCE_OBSERVED + 100 * 86400):
        try:
            build_statement(decision_input_sha256=INPUT, evidence_bundle_sha256=BUNDLE,
                issued_at_epoch=NOW, expires_at_epoch=NOW + 3600,
                nonce="AQEBAQEBAQEBAQEBAQEBAQ",
                source_observed_at_epoch=SOURCE_OBSERVED,
                source_expires_at_epoch=invalid_source_expiry)
        except ValueError as exc:
            assert str(exc) == "invalid_source_window"
        else:
            raise AssertionError("non-24-hour source window accepted")


def test_digest_signature_route_scope_and_partial_tamper_fail_closed():
    statement, review, owner = bundle()
    changes = []
    changed = copy.deepcopy(statement); changed["decisionInputSha256"] = "d" * 64; changes.append((changed, review, owner))
    changed = copy.deepcopy(statement); changed["route"] = "E0/E0.3/B5.3/064B"; changes.append((changed, review, owner))
    changed = copy.deepcopy(statement); changed["cutoverAuthorized"] = True; changes.append((changed, review, owner))
    changed_review = copy.deepcopy(review); changed_review["signature"] = "A" * 86; changes.append((statement, changed_review, owner))
    changed_owner = copy.deepcopy(owner); changed_owner["reviewEnvelopeSha256"] = "e" * 64; changes.append((statement, review, changed_owner))
    for values in changes:
        assert check(*values)["boundedEvidenceAccepted"] is False
    assert check(statement, review, owner, current="f" * 64)["boundedEvidenceAccepted"] is False


def test_role_revocation_nonindependence_expiry_and_replay_fail_closed():
    statement, review, owner = bundle()
    revoked = copy.deepcopy(REGISTRY); revoked["review_key"]["status"] = "REVOKED"
    assert check(statement, review, owner, registry=revoked)["status"] == "INVALID"
    same_domain = copy.deepcopy(REGISTRY); same_domain["owner_key"]["trustDomain"] = "review_org"
    altered_owner = copy.deepcopy(owner); altered_owner["trustDomain"] = "review_org"
    altered_owner["signature"] = signer("owner_key", b"invalid").hex()[:86]
    assert check(statement, review, altered_owner, registry=same_domain)["status"] == "INVALID"
    assert check(statement, review, owner, now=NOW + 3600)["status"] == "INVALID"
    ledger = Ledger()
    assert check(statement, review, owner, ledger=ledger)["syntheticProtocolValid"] is True
    assert check(statement, review, owner, ledger=ledger)["status"] == "INVALID"


def test_signature_envelopes_cannot_outlive_the_source_bound_statement():
    statement, _, _ = bundle(source_bound=True)
    review = build_reviewer_envelope(
        statement_sha256=statement["statementSha256"], key_id="review_key",
        identity_id="reviewer_1", trust_domain="review_org", keyring_sha256=KEYRING,
        issued_at_epoch=NOW, expires_at_epoch=statement["expiresAtEpoch"] + 1,
        nonce="AgICAgICAgICAgICAgICAg", sign=signer)
    owner = build_owner_envelope(
        review_envelope=review, statement_sha256=statement["statementSha256"],
        key_id="owner_key", identity_id="owner_1", trust_domain="owner_org",
        keyring_sha256=KEYRING, issued_at_epoch=NOW,
        expires_at_epoch=statement["expiresAtEpoch"] + 1,
        nonce="AwMDAwMDAwMDAwMDAwMDAw", sign=signer)
    assert check(statement, review, owner,
                 source_window=(SOURCE_OBSERVED, SOURCE_EXPIRES))["status"] == "INVALID"


def test_chat_text_or_unsigned_template_cannot_become_approval():
    statement, review, owner = bundle()
    assert "continue" not in str(statement).lower()
    assert check(statement, {}, owner)["boundedEvidenceAccepted"] is False
    assert check(statement, review, {})["boundedEvidenceAccepted"] is False


def test_unsigned_historical_decision_input_detects_current_drift_and_stays_blocked_owner():
    path = ROOT / "docs/e0-3-bot-b5-3-064a-decision-input.v1.json"
    value = json.loads(path.read_text())
    files = {
        "migration_plan": "docs/e0-3-bot-b5-3-production-migration-plan.v1.json",
        "dirty_data_scan": "docs/e0-3-bot-b5-3-production-dirty-data-scan-rehearsal.v1.json",
        "catalog_drift_rehearsal": "docs/e0-3-bot-b5-3-catalog-security-drift-rehearsal.v1.json",
        "catalog_source_restore_rehearsal": "docs/e0-3-bot-b5-3-catalog-source-restore-rehearsal.v1.json",
        "bootstrap_roles": "deploy/postgres/bootstrap_roles.sql",
        "prepare_database": "deploy/postgres/prepare_database.sql",
        "runtime_privileges": "deploy/postgres/runtime_privileges.sql",
    }
    assert [item["artifactId"] for item in value["artifactDigests"]] == list(files)
    drift = []
    for item in value["artifactDigests"]:
        current = hashlib.sha256((ROOT / files[item["artifactId"]]).read_bytes()).hexdigest()
        if current != item["sha256"]:
            drift.append(item["artifactId"])
    assert drift == ["bootstrap_roles", "prepare_database", "runtime_privileges"]
    assert value["currentDecisionStatus"] == "BLOCKED_OWNER"
    assert value["ownerApprovalPresent"] is False
    assert value["independentReviewerApprovalPresent"] is False
    assert value["cutoverAuthorized"] is False and value["actionAllowed"] is False
