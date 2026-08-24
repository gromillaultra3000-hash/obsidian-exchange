import json
import hashlib
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_capability_verifier import build_capability_verifier_request
from test_e3_testnet_capabilities import NOW, complete

SCRIPT = ROOT / "kairos/scripts/e3_independent_verifier.py"
UNIT = ROOT / "kairos/deploy/kairos-independent-verifier.service"
MANIFEST = ROOT / "kairos/deploy/kairos-independent-verifier.manifest.json"


def bundle(**changes):
    request = build_capability_verifier_request(
        provider="bybit", account_ref="sandbox_1", assessed_at_epoch_ms=NOW + 1)
    response = {"requestId": request["requestId"], "provider": "bybit",
                "accountRef": "sandbox_1", "observations": complete(),
                "containsSecrets": False}
    value = {"request": request, "sourceResponse": response, "containsSecrets": False}
    value.update(changes)
    return value


def run_cli(tmp_path, value):
    path = tmp_path / "evidence.json"
    path.write_text(json.dumps(value))
    return subprocess.run([sys.executable, str(SCRIPT), "--input", str(path)],
                          text=True, capture_output=True, check=False)


def test_offline_cli_validates_existing_evidence_without_enabling_runtime(tmp_path):
    completed = run_cli(tmp_path, bundle())
    assert completed.returncode == 0 and completed.stderr == ""
    output = json.loads(completed.stdout)
    assert output["result"]["status"] == "VERIFIED_OFFLINE"
    assert output["result"]["readinessCheckSatisfied"] is False
    assert output["executionEffect"] == "NONE"
    assert output["actionAllowed"] is False


def test_secret_bearing_or_malformed_bundle_is_bounded_no_go(tmp_path):
    for value in (bundle(containsSecrets=True), {"secret": "must-not-echo"}):
        completed = run_cli(tmp_path, value)
        assert completed.returncode == 1 and completed.stderr == ""
        output = json.loads(completed.stdout)
        assert output["status"] == "NO_GO"
        assert output["reason"] == "INVALID_INPUT"
        assert "must-not-echo" not in completed.stdout


def test_cli_rejects_oversized_input_without_echo(tmp_path):
    path = tmp_path / "large.json"
    path.write_bytes(b"x" * (64 * 1024 + 1))
    completed = subprocess.run(
        [sys.executable, str(SCRIPT), "--input", str(path)],
        text=True, capture_output=True, check=False)
    assert completed.returncode == 1
    assert json.loads(completed.stdout)["reason"] == "INVALID_INPUT"


def test_service_is_inactive_by_design_networkless_read_only_and_unprivileged():
    unit = UNIT.read_text()
    required = (
        "Type=oneshot", "User=kairos-verifier", "Group=kairos-verifier",
        "NoNewPrivileges=true", "PrivateNetwork=true", "PrivateDevices=true",
        "ProtectSystem=strict", "ProtectHome=true", "CapabilityBoundingSet=",
        "AmbientCapabilities=", "RestrictAddressFamilies=AF_UNIX",
        "ReadOnlyPaths=/var/lib/kairos-verifier/existing-evidence.json",
    )
    for item in required:
        assert item in unit
    assert "WantedBy=" not in unit
    assert "EnvironmentFile=" not in unit
    assert "ReadWritePaths=" not in unit


def test_artifact_has_no_network_sdk_secret_or_active_action_surface():
    source = SCRIPT.read_text()
    for forbidden in ("requests", "httpx", "aiohttp", "socket", "ccxt",
                      "os.environ", "apiKey", "apiSecret", ".withdraw(",
                      ".transfer(", "subprocess"):
        assert forbidden not in source


def test_manifest_content_binds_exact_secret_free_inactive_artifacts():
    manifest = json.loads(MANIFEST.read_text())
    assert set(manifest) == {
        "schemaVersion", "artifactName", "artifactVersion", "files",
        "containsSecrets", "networkRequired", "installationAuthorized",
        "runtimeEnableAuthorized",
    }
    assert manifest["schemaVersion"] == "independent-verifier-artifact-manifest.v1"
    assert manifest["containsSecrets"] is False
    assert manifest["networkRequired"] is False
    assert manifest["installationAuthorized"] is False
    assert manifest["runtimeEnableAuthorized"] is False
    assert [item["path"] for item in manifest["files"]] == [
        "deploy/kairos-independent-verifier.service",
        "scripts/e3_independent_verifier.py",
    ]
    for item in manifest["files"]:
        path = ROOT / "kairos" / item["path"]
        assert path.is_file() and not path.is_symlink()
        assert hashlib.sha256(path.read_bytes()).hexdigest() == item["sha256"]
