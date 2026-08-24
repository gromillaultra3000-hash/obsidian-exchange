import copy
import inspect
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_promotion_preflight import (
    CHECKS, MAX_EVIDENCE_AGE_MS, build_promotion_preflight,
    validate_promotion_preflight,
)

DIGEST = "a" * 64


def evidence(**changes):
    value = {field: True for field, _ in CHECKS}
    value.update({
        "collectedAtEpochMs": 2_000_000,
        "snapshotSha256": DIGEST,
        "tableInventorySha256": "b" * 64,
        "aclInventorySha256": "c" * 64,
        "rollbackPlanSha256": "d" * 64,
        "proposalMigrationSha256": "e" * 64,
        "proposalAclSha256": "f" * 64,
    })
    value.update(changes)
    return value


def preflight(**changes):
    return build_promotion_preflight(
        evidence=evidence(**changes), evaluated_at_epoch_ms=2_000_001)


def test_complete_fresh_evidence_only_allows_offline_promotion_review():
    value = preflight()
    assert value["status"] == "PROMOTION_REVIEW_READY_OFFLINE"
    assert value["promotionReviewEligible"] is True and value["blockers"] == []
    assert validate_promotion_preflight(value) == value
    for field in ("migrationPromotionPerformed", "productionMigrationApplied",
                  "productionAclApplied", "routeConnected", "featureGatesChanged",
                  "actionAllowed"):
        assert value[field] is False


@pytest.mark.parametrize(("field", "blocker"), CHECKS)
def test_every_required_check_independently_blocks_review(field, blocker):
    value = preflight(**{field: False})
    assert value["status"] == "NO_GO"
    assert value["promotionReviewEligible"] is False
    assert value["blockers"] == [blocker]


def test_stale_or_future_evidence_fails_closed():
    stale = build_promotion_preflight(
        evidence=evidence(), evaluated_at_epoch_ms=2_000_000 + MAX_EVIDENCE_AGE_MS + 1)
    assert stale["blockers"] == ["EVIDENCE_STALE"]
    future = build_promotion_preflight(
        evidence=evidence(collectedAtEpochMs=2_002_000),
        evaluated_at_epoch_ms=2_000_000)
    assert future["blockers"] == ["EVIDENCE_FROM_FUTURE"]


@pytest.mark.parametrize("field", [
    "status", "promotionReviewEligible", "blockers", "migrationPromotionPerformed",
    "productionMigrationApplied", "productionAclApplied", "routeConnected",
    "featureGatesChanged", "actionAllowed", "preflightId",
])
def test_tamper_cannot_claim_deploy_or_action(field):
    value = copy.deepcopy(preflight())
    value[field] = (
        "NO_GO" if field == "status"
        else False if field == "promotionReviewEligible"
        else True
    )
    with pytest.raises(ValueError):
        validate_promotion_preflight(value)


def test_contract_has_no_environment_file_route_database_or_execution_surface():
    source = inspect.getsource(sys.modules["core.e4_promotion_preflight"])
    for forbidden in ("os.environ", "getenv", "Path(", "open(", "FastAPI", "APIRouter",
                      "sqlite", "psycopg", "subprocess", "requests", "httpx"):
        assert forbidden not in source


def test_workspace_remains_in_pre_promotion_state():
    assert (ROOT / "deploy/postgres/proposals/025_e4_action_handoff.sql").is_file()
    assert (ROOT / "deploy/postgres/proposals/025_e4_action_handoff_acl.sql").is_file()
    assert not (ROOT / "deploy/postgres/025_e4_action_handoff.sql").exists()
    runtime = "\n".join(
        path.read_text(errors="replace") for path in (
            ROOT / "relay-fastapi/main.py",
            ROOT / "deploy/systemd/relay-fastapi.service",
        ) if path.is_file())
    assert "/api/wallet/private-action/confirm" not in runtime
    assert "E4_ACTION_HANDOFF_ENABLED" not in runtime
    assert "E4_ACTION_ROUTE_ENABLED" not in runtime
