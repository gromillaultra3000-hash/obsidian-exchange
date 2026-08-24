import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_native_signing_matrix_is_exact_and_non_accepting():
    matrix = json.loads((ROOT / "docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    item = next(feature for feature in matrix["features"] if feature["id"] == "NATIVE_SIGNING")
    expected = {
        "telegramBot": ("N/A", "NOT_IMPLEMENTED"),
        "site": ("READ_ONLY", "NOT_IMPLEMENTED"),
        "miniApp": ("READ_ONLY", "NOT_IMPLEMENTED"),
        "admin": ("N/A", "NOT_IMPLEMENTED"),
        "api": ("READ_ONLY", "PARTIAL"),
        "native": ("REQUIRED", "PARTIAL"),
    }
    assert item["overallStatus"] == "PARTIAL_NOT_ACCEPTED"
    assert item["moneyWriter"] is True
    assert item["custodyCritical"] is True
    assert {name: (cell["mode"], cell["implementation"])
            for name, cell in item["cells"].items()} == expected
    assert "NATIVE_SIGNING" not in matrix["omittedFeatureFamilies"]
    assert "LUMI_CONTROL_PLANE" not in matrix["omittedFeatureFamilies"]


def test_native_observation_proves_no_keys_signatures_or_production_action():
    value = json.loads((ROOT / "docs/e0-4-native-signing-runtime-observation.v1.json").read_text())
    assert value["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    for field in ("productionMutation", "networkUsed", "keyMaterialObserved",
                  "keyMaterialGenerated", "signatureGenerated", "transactionBroadcast",
                  "mobileBuildProduced"):
        assert value[field] is False
    assert all(item["result"] == "PASS" for item in value["verification"])
    assert sum(item["tests"] for item in value["verification"]) == 141


def test_native_artifacts_are_hash_bound_and_not_deployed():
    value = json.loads((ROOT / "docs/e0-4-native-signing-runtime-observation.v1.json").read_text())
    for artifact in value["artifacts"]:
        path = ROOT / artifact["path"]
        assert path.is_file()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == artifact["sha256"]
    runtime = value["runtime"]
    assert runtime["deployedNativeArtifactPresent"] is False
    assert runtime["iosApplicationPresent"] is False
    assert runtime["androidApplicationPresent"] is False
    assert runtime["e5PythonContractsDeployed"] is False


def test_scaffold_and_contracts_remain_fail_closed():
    core = (ROOT / "native-wallet/crates/wallet-core/src/lib.rs").read_text()
    ffi = (ROOT / "native-wallet/crates/wallet-ffi/src/lib.rs").read_text()
    consent = (ROOT / "relay/core/e5_signing_consent.py").read_text()
    boundary = (ROOT / "relay/core/e5_key_boundary.py").read_text()
    assert "signing_available: false" in core
    assert "production_action_allowed: false" in core
    assert "signing_allowed: false" in ffi
    assert "production_action_allowed: false" in ffi
    assert '"signaturePresent": False' in consent
    assert '"signingAllowed": False' in consent
    assert '"signingImplemented": False' in boundary


def test_external_ton_routes_exist_but_are_not_native_signing():
    value = json.loads((ROOT / "docs/e0-4-native-signing-runtime-observation.v1.json").read_text())
    correction = value["externalTonConnectCorrection"]
    assert correction["checkoutSendRequestRoutePresent"] is True
    assert correction["checkoutSendSignedRoutePresent"] is True
    assert correction["deployedSendRequestRoutePresent"] is True
    assert correction["deployedSendSignedRoutePresent"] is True
    assert correction["nativeSigningEvidence"] is False
    checkout = (ROOT / "relay-fastapi/main.py").read_text()
    deployed = Path("/opt/obsidian-exchange/relay-fastapi/main.py").read_text()
    for source in (checkout, deployed):
        assert '/api/wallet/send-request' in source
        assert '/api/wallet/send-signed' in source
    assert all(review["disposition"] == "ACCEPTED_WITH_CORRECTION"
               for review in value["independentReviews"])
