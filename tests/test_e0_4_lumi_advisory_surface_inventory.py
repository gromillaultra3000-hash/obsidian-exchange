import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _evidence():
    return json.loads((ROOT / "docs/e0-4-lumi-advisory-runtime-observation.v1.json").read_text())


def test_lumi_matrix_is_exact_and_non_authorizing():
    matrix = json.loads((ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    item = next(feature for feature in matrix["features"] if feature["id"] == "LUMI_ADVISORY")
    expected = {
        "telegramBot": ("N/A", "NOT_IMPLEMENTED"),
        "site": ("N/A", "NOT_IMPLEMENTED"),
        "miniApp": ("N/A", "NOT_IMPLEMENTED"),
        "admin": ("OPERATOR_ONLY", "PARTIAL"),
        "api": ("OPERATOR_ONLY", "PARTIAL"),
        "native": ("N/A", "NOT_IMPLEMENTED"),
    }
    assert item["overallStatus"] == "PARTIAL_NOT_ACCEPTED"
    assert item["moneyWriter"] is False
    assert item["advisoryOnly"] is True
    assert {name: (cell["mode"], cell["implementation"])
            for name, cell in item["cells"].items()} == expected
    assert "LUMI_ADVISORY" not in matrix["omittedFeatureFamilies"]
    assert "LUMI_CONTROL_PLANE" not in matrix["omittedFeatureFamilies"]


def test_lumi_observation_is_read_only_and_secret_free():
    value = _evidence()
    assert value["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    for field in ("productionMutation", "credentialsUsed", "secretValuesRead",
                  "customerDataRead", "advisoryInvocationsMade",
                  "externalProviderCallsMade", "moneyWritersExercised"):
        assert value[field] is False
    assert value["authorityFinding"]["currentDirectMoneyOrAclAuthority"] is False
    assert value["runtime"]["lumiService"]["healthStatusCode"] == 200
    assert {item["statusCode"] for item in value["runtime"]["unauthenticatedFences"]} == {401}


def test_lumi_artifacts_match_deployment_and_hashes():
    for artifact in _evidence()["artifacts"]:
        checkout = ROOT / artifact["path"]
        deployed = Path(artifact["deployedPath"])
        assert checkout.is_file() and deployed.is_file()
        assert hashlib.sha256(checkout.read_bytes()).hexdigest() == artifact["sha256"]
        assert hashlib.sha256(deployed.read_bytes()).hexdigest() == artifact["sha256"]
        assert artifact["equal"] is True


def test_live_bridge_is_not_the_frozen_wire_and_does_not_gate_execution():
    bridge = (ROOT / "kairos/app/lumi_bridge.py").read_text()
    engine = (ROOT / "kairos/app/kairos_engine.py").read_text()
    lumi_resolver = (ROOT / "lumi/lumi/app/conflict/deterministic_resolver.py").read_text()
    frozen = (ROOT / "kairos/app/shadow_advisory_wire.py").read_text()
    assert '_post("/conflict/resolve"' in bridge
    assert 'verdict["combinedVerdict"] = verdict.get("verdict")' in bridge
    assert "actionAllowed=True" in lumi_resolver
    assert "self._advisory_committee(cand)" in engine
    assert "execution = self.execute_candidate(cand)" in engine
    assert "HardVerdict.HOLD" in frozen


def test_material_risks_and_independent_reviews_are_recorded():
    value = _evidence()
    ids = {item["id"] for item in value["riskFindings"]}
    assert {"LIVE_PATH_NOT_FROZEN_WIRE", "FAILURE_NOT_HOLD", "ADVISORY_IGNORED",
            "AUTH_REPLAY_BOUNDS", "DATA_MINIMIZATION", "AUDIT_RETENTION",
            "PROVIDER_CONCENTRATION", "UI_TRUTH", "PROVENANCE"} <= ids
    assert len(value["independentReviews"]) == 2
    assert all(item["disposition"] == "PARTIAL_NOT_ACCEPTED"
               for item in value["independentReviews"])
