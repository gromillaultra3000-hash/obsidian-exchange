import copy
import json
import sqlite3
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from repositories.e4_action_handoff_store import SQLiteE4ActionHandoffStore
from services.e4_private_action_invoker import (
    E4TestOnlyHandoffStore, invoke_private_action_test_only,
    validate_test_invocation_result,
)
from test_e4_action_handoff_store import build, schema


def invocation_args(path, side="BUY_CRYPTO"):
    chain = build(side)
    return {"store": E4TestOnlyHandoffStore(SQLiteE4ActionHandoffStore(path)),
            "preview": chain.pop("preview", None), **chain}


def complete_args(path, side="BUY_CRYPTO"):
    # build() returns the persistence tail; reconstruct upstream objects from IDs is
    # intentionally impossible, so use the same deterministic test helpers directly.
    from test_e4_action_acknowledgement import acknowledge, challenge
    from test_e4_action_preview import preview
    from test_e4_action_handoff_store import ACTOR_USER_ID, PRINCIPAL, evidence
    from core.e4_confirmation_draft import build_confirmation_draft
    from core.e4_private_action_adapter import assess_private_action_draft
    from core.e4_action_reservation import build_action_reservation_request
    import hashlib
    action = preview(side=side); gate = challenge(action); receipt = acknowledge(action, gate)
    if side == "BUY_CRYPTO":
        destination = {"kind": "WALLET_ADDRESS", "network": "bitcoin",
                       "destinationFingerprintSha256": hashlib.sha256(b"destination").hexdigest()}
        order = {"user_id": ACTOR_USER_ID, "username": "tester", "currency": "BTC",
                 "rub_amount": "10000", "destination": "destination", "network": "bitcoin",
                 "agreed_rate": "10000000", "agreed_crypto_amount": "0.001", "web_user_id": 3}
    else:
        payout = {"sbp_phone": "+79990000000", "payout_method": "sbp", "payout_bank": "bank",
                  "payout_details": "+79990000000", "payout_name": "User"}
        import json as json_module
        digest = hashlib.sha256(json_module.dumps(
            payout, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        destination = {"kind": "BANK_ACCOUNT", "network": None,
                       "destinationFingerprintSha256": digest}
        order = {"user_id": ACTOR_USER_ID, "currency": "BTC", "crypto_amount": "0.001",
                 "rub_amount": "10000", "receive_address": "exchange_deposit", **payout}
    key = "confirm_invoker"
    draft = build_confirmation_draft(
        preview=action, challenge=gate, acknowledgement_receipt=receipt,
        idempotency_key=key, destination_summary=destination,
        created_at_epoch_ms=receipt["acknowledgedAtEpochMs"] + 1)
    assessed_at = draft["createdAtEpochMs"] + 1
    assessment = assess_private_action_draft(
        draft=draft, preview=action, challenge=gate, acknowledgement_receipt=receipt,
        idempotency_key=key, principal_ref=PRINCIPAL, actor_user_id=ACTOR_USER_ID,
        evidence=evidence(draft, assessed_at), assessed_at_epoch_ms=assessed_at)
    reservation = build_action_reservation_request(
        draft=draft, assessment=assessment, requested_at_epoch_ms=assessed_at + 1,
        expires_at_epoch_ms=min(assessed_at + 10_000, draft["quoteExpiresAtEpochMs"]))
    return dict(store=E4TestOnlyHandoffStore(SQLiteE4ActionHandoffStore(path)), preview=action,
                challenge=gate, acknowledgement_receipt=receipt, draft=draft,
                idempotency_key=key, assessment=assessment, reservation=reservation,
                order=order, trusted_principal_ref=PRINCIPAL,
                trusted_actor_user_id=ACTOR_USER_ID, trusted_web_user_id=3)


@pytest.mark.parametrize("side,kind", [("BUY_CRYPTO", "BUY_ORDER"),
                                        ("SELL_CRYPTO", "SELL_ORDER")])
def test_complete_chain_returns_only_bounded_created_and_replay_metadata(side, kind):
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db"); schema(path)
        args = complete_args(path, side)
        created = invoke_private_action_test_only(**args)
        replayed = invoke_private_action_test_only(**args)
        assert created["status"] == "CREATED_TEST_ONLY"
        assert replayed["status"] == "REPLAYED_TEST_ONLY"
        assert created["resultKind"] == replayed["resultKind"] == kind
        assert created["resultId"] == replayed["resultId"] == 1
        assert created["productionInvocationAllowed"] is False
        assert created["routeConnected"] is False
        encoded = json.dumps(created)
        for raw in ("destination", "+79990000000", "exchange_deposit"):
            assert raw not in encoded
        assert validate_test_invocation_result(created) == created


def test_non_test_store_and_tampered_chain_never_call_handoff():
    class Spy:
        calls = 0
        def handoff(self, **kwargs): self.calls += 1
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db"); schema(path)
        args, spy = complete_args(path), Spy(); args["store"] = spy
        with pytest.raises(ValueError): invoke_private_action_test_only(**args)
        assert spy.calls == 0
        args["store"] = E4TestOnlyHandoffStore(spy)
        args["draft"] = copy.deepcopy(args["draft"]); args["draft"]["actor"] = "tamper"
        with pytest.raises(ValueError): invoke_private_action_test_only(**args)
        assert spy.calls == 0


def test_handoff_store_has_no_boolean_test_only_constructor_switch():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db")
        with pytest.raises(TypeError): SQLiteE4ActionHandoffStore(path, test_only=True)


@pytest.mark.parametrize("field,value", [
    ("trusted_principal_ref", "web_user_2"),
    ("trusted_actor_user_id", 8),
    ("trusted_web_user_id", 4),
])
def test_trusted_identity_drift_never_reaches_handoff(field, value):
    class Spy:
        calls = 0
        def handoff(self, **kwargs): self.calls += 1
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db"); schema(path)
        args, spy = complete_args(path), Spy(); args["store"] = E4TestOnlyHandoffStore(spy)
        args[field] = value
        with pytest.raises(ValueError): invoke_private_action_test_only(**args)
        assert spy.calls == 0


def test_order_actor_drift_never_reaches_injected_handoff():
    class Spy:
        calls = 0
        def handoff(self, **kwargs): self.calls += 1
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db"); schema(path)
        args, spy = complete_args(path), Spy(); args["store"] = E4TestOnlyHandoffStore(spy)
        args["order"] = copy.deepcopy(args["order"]); args["order"]["user_id"] = 8
        with pytest.raises(ValueError): invoke_private_action_test_only(**args)
        assert spy.calls == 0


def test_assessment_cannot_self_select_principal_against_trusted_context():
    class Spy:
        calls = 0
        def handoff(self, **kwargs): self.calls += 1
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db"); schema(path)
        args, spy = complete_args(path), Spy(); args["store"] = E4TestOnlyHandoffStore(spy)
        args["assessment"] = copy.deepcopy(args["assessment"])
        args["assessment"]["principalRef"] = "web_user_2"
        with pytest.raises(ValueError): invoke_private_action_test_only(**args)
        assert spy.calls == 0


def test_store_failure_is_bounded_without_exception_or_raw_payload():
    class Broken:
        def handoff(self, **kwargs): raise RuntimeError("sensitive internal detail")
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db"); schema(path)
        args = complete_args(path); args["store"] = E4TestOnlyHandoffStore(Broken())
        result = invoke_private_action_test_only(**args)
        assert result["status"] == "NO_GO" and result["reason"] == "STORE_ERROR"
        assert "sensitive internal detail" not in json.dumps(result)
        assert result["executionEffect"] == "NONE"


def test_result_tamper_cannot_claim_production_route_or_action():
    with tempfile.TemporaryDirectory() as directory:
        path = str(Path(directory) / "invoke.db"); schema(path)
        result = invoke_private_action_test_only(**complete_args(path))
        for field in ("productionInvocationAllowed", "routeConnected", "actionAllowed"):
            changed = copy.deepcopy(result); changed[field] = True
            with pytest.raises(ValueError): validate_test_invocation_result(changed)


def test_invoker_has_no_http_provider_secret_or_logging_surface():
    source = (ROOT / "relay/services/e4_private_action_invoker.py").read_text()
    for forbidden in ("FastAPI", "APIRouter", "requests", "httpx", "aiohttp", "socket",
                      "os.environ", "apiKey", "apiSecret", "logger", "print("):
        assert forbidden not in source
