import hashlib
import json
from pathlib import Path


ROOT = Path("/root")
EVIDENCE = ROOT / "docs/e0-4-post-25-closure-reconciliation.v1.json"
MATRIX = ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json"


def sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_baseline_is_25_but_closure_is_explicitly_false():
    evidence = json.loads(EVIDENCE.read_text())
    matrix = json.loads(MATRIX.read_text())
    assert len(matrix["features"]) == evidence["baseline"]["declaredFeatureFamilies"] == 25
    conclusion = evidence["coverageConclusion"]
    assert conclusion["priorTwentyFiveFamiliesComplete"] is False
    for key, value in conclusion.items():
        if key != "exactHttpUniverseEnumerated":
            assert value is False


def test_hash_bound_deployed_http_and_edge_sources_are_current():
    evidence = json.loads(EVIDENCE.read_text())
    for component in ("relay", "kairos", "lumi"):
        item = evidence["httpUniverse"][component]
        assert sha(item["entrypoint"]) == item["sha256"]
    for name, digest in evidence["httpUniverse"]["nginx"]["configSha256"].items():
        assert sha(f"/etc/nginx/sites-enabled/{name}") == digest
    assert evidence["httpUniverse"]["threeFastApiInferredRouteObjects"] == 346
    assert evidence["httpUniverse"]["combinedFrameworkRouteObjectsObserved"] == 375


def test_material_omissions_are_unique_and_next_item_is_first_one():
    evidence = json.loads(EVIDENCE.read_text())
    ids = [item["id"] for item in evidence["newMaterialFamilies"]]
    assert ids == [
        "RATE_LOCKS", "DEPLOYMENT_RELEASE_AUTOMATION", "EDITORIAL_NEWS_DELIVERY",
        "TELEGRAM_CHANNEL_POST_PROCESSING", "LEGACY_PAYMENT_EDGE_UPSTREAM"
    ]
    assert len(ids) == len(set(ids))
    assert all(item["anchors"] for item in evidence["newMaterialFamilies"])
    assert evidence["nextCanonicalItem"].startswith("Classify RATE_LOCKS")


def test_observation_has_no_runtime_effect_authority():
    evidence = json.loads(EVIDENCE.read_text())
    for key in ("productionMutation", "authenticatedCallsMade", "secretValuesRead",
                "customerDataRead", "externalProviderCallsMade",
                "moneyWritersExercised", "servicesRestarted"):
        assert evidence[key] is False
    assert evidence["status"] == "IN_PROGRESS"
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert len(evidence["independentReviews"]) == 3
