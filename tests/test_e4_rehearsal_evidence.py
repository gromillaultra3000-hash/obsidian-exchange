import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_rehearsal_evidence import collect_rehearsal_evidence


def manifest():
    return json.loads((ROOT / "deploy/postgres/proposals/"
                       "e4_full_snapshot_rehearsal_manifest.json").read_text())


def observation(**changes):
    value = {
        "targetClass": "ISOLATED_DISPOSABLE_POSTGRESQL",
        "targetFingerprintSha256": "1" * 64, "snapshotSha256": "2" * 64,
        "tableInventorySha256": "3" * 64, "aclInventorySha256": "4" * 64,
        "fullSnapshotMatched": True, "tableInventoryCaptured": True,
        "aclInventoryCaptured": True, "rollbackBoundaryVerified": True,
        "handoffGateExplicitlyFalse": True, "routeGateExplicitlyFalse": True,
        "confirmRouteAbsent": True, "active025MigrationAbsent": True,
        "proposalMigrationSha256": "c1212dae3e431e745c7f2cd28ab993b681da4c0c5f909d494ffe6126e069af56",
        "proposalAclSha256": "f481217d86bd4b51c07f751b5a88391024ecea16bd345f7af8fa010d1159b1b4",
        "rollbackPlanSha256": "fc88b29bc81ff30f71bea2ca965bf6d897f4aed5ce7b1539a72bba3995d5b2ef",
        "connectionMaterialPresent": False, "productionContacted": False,
        "writePerformed": False,
    }
    value.update(changes)
    return value


def test_complete_secret_free_isolated_measurement_is_only_offline_review_ready():
    value = collect_rehearsal_evidence(
        manifest=manifest(), observation=observation(), collected_at_epoch_ms=2_000_000)
    assert value["status"] == "PROMOTION_REVIEW_READY_OFFLINE"
    assert value["connectionMaterialRedacted"] is True
    assert value["executionEffect"] == "NONE"
    assert value["promotionPerformed"] is value["actionAllowed"] is False
    encoded = json.dumps(value)
    assert "postgresql://" not in encoded and "password" not in encoded.lower()


@pytest.mark.parametrize("changes", [
    {"handoffGateExplicitlyFalse": False}, {"routeGateExplicitlyFalse": False},
    {"confirmRouteAbsent": False}, {"active025MigrationAbsent": False},
    {"productionContacted": True}, {"writePerformed": True},
    {"connectionMaterialPresent": True}, {"targetClass": "PRODUCTION"},
])
def test_unsafe_or_connected_measurement_is_no_go(changes):
    value = collect_rehearsal_evidence(
        manifest=manifest(), observation=observation(**changes),
        collected_at_epoch_ms=2_000_000)
    assert value["status"] == "NO_GO"
    assert value["preflight"]["promotionReviewEligible"] is False
    if "productionContacted" in changes:
        assert value["productionContacted"] is changes["productionContacted"]
    if "writePerformed" in changes:
        assert value["writePerformed"] is changes["writePerformed"]
    if "connectionMaterialPresent" in changes:
        assert value["connectionMaterialRedacted"] is not changes["connectionMaterialPresent"]


def test_artifact_drift_against_frozen_manifest_is_rejected():
    changed = observation(proposalAclSha256="0" * 64)
    with pytest.raises(ValueError, match="frozen manifest"):
        collect_rehearsal_evidence(
            manifest=manifest(), observation=changed, collected_at_epoch_ms=2_000_000)


def test_observation_cannot_smuggle_connection_material_field():
    changed = copy.deepcopy(observation())
    changed["databaseUrl"] = "postgresql://secret"
    with pytest.raises(ValueError, match="fields differ"):
        collect_rehearsal_evidence(
            manifest=manifest(), observation=changed, collected_at_epoch_ms=2_000_000)


def test_frozen_manifest_matches_workspace_artifacts():
    import hashlib
    value = manifest()
    for path_field, digest_field in (
        ("proposalMigrationPath", "proposalMigrationSha256"),
        ("proposalAclPath", "proposalAclSha256"),
        ("rollbackPlanPath", "rollbackPlanSha256"),
    ):
        assert hashlib.sha256((ROOT / value[path_field]).read_bytes()).hexdigest() \
            == value[digest_field]


def test_collector_has_no_database_network_environment_or_execution_surface():
    source = (ROOT / "relay/core/e4_rehearsal_evidence.py").read_text()
    for forbidden in ("psycopg", "sqlite", "socket", "subprocess", "os.environ",
                      "getenv", "requests", "httpx", "FastAPI", "APIRouter"):
        assert forbidden not in source
