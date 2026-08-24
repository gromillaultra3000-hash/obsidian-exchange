import copy
import hashlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_route_authorization import assess_route_authorization, validate_route_authorization
from test_e4_action_handoff_store import build


def authorization(**changes):
    chain = build()
    assessed = chain["assessment"]["assessedAtEpochMs"] + 2
    values = dict(assessment=chain["assessment"], reservation=chain["reservation"],
                  web_user_id=3, actor_user_id=chain["assessment"]["actorUserId"],
                  principal_ref=chain["assessment"]["principalRef"],
                  session_fingerprint_sha256=hashlib.sha256(b"session").hexdigest(),
                  csrf_evidence_sha256=hashlib.sha256(b"csrf").hexdigest(),
                  authenticated_at_epoch_ms=assessed - 1,
                  assessed_at_epoch_ms=assessed,
                  handoff_enabled=False, route_enabled=False)
    values.update(changes)
    return assess_route_authorization(**values)


def test_both_gates_default_false_and_independently_block_route():
    value = authorization()
    assert value["status"] == "NO_GO"
    assert value["blockers"] == ["HANDOFF_FEATURE_DISABLED", "ROUTE_FEATURE_DISABLED"]
    assert value["productionInvocationAllowed"] is False
    assert value["routeConnected"] is False
    assert validate_route_authorization(value) == value
    assert authorization(handoff_enabled=True)["blockers"] == ["ROUTE_FEATURE_DISABLED"]
    assert authorization(route_enabled=True)["blockers"] == ["HANDOFF_FEATURE_DISABLED"]


def test_synthetic_both_gates_only_satisfy_offline_preconditions():
    value = authorization(handoff_enabled=True, route_enabled=True)
    assert value["status"] == "PRECONDITIONS_SATISFIED_OFFLINE"
    assert value["routeInvocationEligible"] is True
    assert value["productionMigrationApplied"] is False
    assert value["productionAclVerified"] is False
    assert value["productionInvocationAllowed"] is False
    assert value["actionAllowed"] is False


def test_stale_future_expired_or_mismatched_actor_fails_closed():
    base = authorization()
    assert "AUTHENTICATION_STALE" in authorization(
        authenticated_at_epoch_ms=base["assessedAtEpochMs"] - 300_001)["blockers"]
    assert "AUTHENTICATION_FUTURE" in authorization(
        authenticated_at_epoch_ms=base["assessedAtEpochMs"] + 1001)["blockers"]
    assert "RESERVATION_EXPIRED" in authorization(
        assessed_at_epoch_ms=build()["reservation"]["expiresAtEpochMs"] + 1)["blockers"]
    with pytest.raises(ValueError): authorization(actor_user_id=999)


@pytest.mark.parametrize("field", ["productionMigrationApplied", "productionAclVerified",
                                    "productionInvocationAllowed", "routeConnected",
                                    "actionAllowed"])
def test_authorization_tamper_cannot_claim_production_or_route(field):
    changed = copy.deepcopy(authorization())
    changed[field] = True
    with pytest.raises(ValueError): validate_route_authorization(changed)


def test_contract_has_no_http_database_secret_or_execution_surface():
    source = (ROOT / "relay/core/e4_route_authorization.py").read_text()
    for forbidden in ("FastAPI", "APIRouter", "sqlite", "psycopg", "requests", "httpx",
                      "socket", "os.environ", "apiKey", "apiSecret", "time.time"):
        assert forbidden not in source
