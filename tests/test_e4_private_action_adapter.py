import copy
import hashlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_private_action_adapter import (
    CHECKS, MAX_EVIDENCE_AGE_MS, assess_private_action_draft,
    build_server_check_evidence, validate_private_action_assessment,
    validate_server_check_evidence,
)
from test_e4_confirmation_draft import flow

PRINCIPAL = "web_user_1"
ACTOR_USER_ID = 7


def evidence(draft, observed_at, principal=PRINCIPAL,
             actor_user_id=ACTOR_USER_ID, **outcomes):
    return [build_server_check_evidence(
        draft_id=draft["draftId"], principal_ref=principal, check_id=check,
        actor_user_id=actor_user_id,
        observed_at_epoch_ms=observed_at, outcome=outcomes.get(check, "PASS"),
        evidence_sha256=hashlib.sha256(check.encode()).hexdigest())
        for check in CHECKS]


def assessment(side="BUY_CRYPTO", **outcomes):
    values, draft = flow(side)
    assessed_at = draft["createdAtEpochMs"] + 1
    proof = evidence(draft, assessed_at, **outcomes)
    args = dict(draft=draft, preview=values["preview"], challenge=values["challenge"],
                acknowledgement_receipt=values["acknowledgement_receipt"],
                idempotency_key=values["idempotency_key"], principal_ref=PRINCIPAL,
                actor_user_id=ACTOR_USER_ID,
                evidence=proof, assessed_at_epoch_ms=assessed_at)
    return args, assess_private_action_draft(**args)


@pytest.mark.parametrize("side,mapping", [
    ("BUY_CRYPTO", "BUY_ORDER_CREATION"), ("SELL_CRYPTO", "SELL_ORDER_CREATION"),
])
def test_all_independent_checks_map_private_draft_offline_without_invocation(side, mapping):
    args, result = assessment(side)
    assert result["status"] == "SERVER_CHECKS_PASSED_OFFLINE"
    assert result["workflowMapping"] == mapping
    assert result["serverAuthenticationSatisfied"] is True
    assert result["serverStateChecksSatisfied"] is True
    assert result["workflowInvocationEligible"] is True
    assert result["routeConnected"] is False
    assert result["persisted"] is False
    assert result["moneyIntentAllowed"] is False
    assert result["actionAllowed"] is False
    assert validate_private_action_assessment(
        json.loads(json.dumps(result)), draft=args["draft"], preview=args["preview"],
        challenge=args["challenge"],
        acknowledgement_receipt=args["acknowledgement_receipt"],
        idempotency_key=args["idempotency_key"], principal_ref=PRINCIPAL) == result


def test_each_server_check_fails_independently():
    for check in CHECKS:
        _, result = assessment(**{check: "FAIL"})
        assert result["status"] == "NO_GO"
        assert result["blockers"] == [check + "_FAIL"]
        assert result["workflowInvocationEligible"] is False


def test_stale_future_wrong_principal_duplicate_and_secret_evidence_fail_closed():
    args, _ = assessment()
    args["evidence"] = evidence(
        args["draft"], args["assessed_at_epoch_ms"] - MAX_EVIDENCE_AGE_MS - 1)
    assert all(item.endswith("_STALE") for item in assess_private_action_draft(**args)["blockers"])
    args, _ = assessment()
    args["evidence"] = evidence(args["draft"], args["assessed_at_epoch_ms"] + 1001)
    assert all(item.endswith("_FUTURE") for item in assess_private_action_draft(**args)["blockers"])
    args, _ = assessment()
    args["evidence"] = evidence(args["draft"], args["assessed_at_epoch_ms"], principal="other")
    with pytest.raises(ValueError):
        assess_private_action_draft(**args)
    args, _ = assessment()
    args["evidence"][-1] = copy.deepcopy(args["evidence"][0])
    with pytest.raises(ValueError):
        assess_private_action_draft(**args)
    changed = build_server_check_evidence(
        draft_id=args["draft"]["draftId"], principal_ref=PRINCIPAL,
        actor_user_id=ACTOR_USER_ID,
        check_id=CHECKS[0], observed_at_epoch_ms=args["assessed_at_epoch_ms"],
        outcome="PASS", evidence_sha256="0" * 64)
    changed["containsSecrets"] = True
    with pytest.raises(ValueError):
        validate_server_check_evidence(changed)


@pytest.mark.parametrize("field", ["routeConnected", "persisted", "moneyIntentAllowed",
                                    "actionAllowed"])
def test_assessment_tamper_cannot_connect_route_persist_or_execute(field):
    args, result = assessment()
    changed = copy.deepcopy(result)
    changed[field] = True
    with pytest.raises(ValueError):
        validate_private_action_assessment(
            changed, draft=args["draft"], preview=args["preview"],
            challenge=args["challenge"],
            acknowledgement_receipt=args["acknowledgement_receipt"],
            idempotency_key=args["idempotency_key"], principal_ref=PRINCIPAL)


def test_adapter_has_no_database_route_network_secret_or_execution_surface():
    source = (ROOT / "relay/core/e4_private_action_adapter.py").read_text()
    for forbidden in ("sqlite", "psycopg", "FastAPI", "APIRouter", "requests", "httpx",
                      "aiohttp", "socket", "os.environ", "apiKey", "apiSecret",
                      "privateKey", "send_crypto", "subprocess", "time.time"):
        assert forbidden not in source
