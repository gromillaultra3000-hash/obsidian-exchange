import hashlib
import json
from pathlib import Path


ROOT = Path("/root")
EVIDENCE = ROOT / "docs/e0-4-deployment-release-automation-runtime-observation.v1.json"


def sha(path: str) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def test_controller_units_state_and_effective_runtime_are_hash_bound():
    evidence = json.loads(EVIDENCE.read_text())
    assert sha(evidence["source"]["scriptPath"]) == evidence["source"]["scriptSha256"]
    runtime = evidence["runtime"]
    for path_key, digest_key in (("timerPath", "timerSha256"), ("servicePath", "serviceSha256"),
                                 ("statePath", "stateSha256")):
        assert sha(runtime[path_key]) == runtime[digest_key]
    for item in evidence["effectiveRuntimeDrift"]:
        assert sha(item["dropInPath"]) == item["dropInSha256"]
        assert item["effectiveSourcePrefix"] == "/opt/obsidian-exchange"


def test_script_has_false_success_and_no_artifact_promotion_or_rollback():
    source = Path("/root/deploy.sh").read_text()
    assert 'systemctl is-active relay-fastapi && echo "relay-fastapi: OK"' in source
    assert '|| echo "relay-fastapi: FAILED"' in source
    assert 'echo "$NEW_REV" > "$STATE"' in source
    assert "git pull origin master" in source
    for required_absence in ("git verify-commit", "git verify-tag", "--ff-only", "flock", "/opt/obsidian-exchange"):
        assert required_absence not in source
    assert "rollback" not in source.lower()


def test_six_surfaces_and_acceptance_are_fail_closed():
    evidence = json.loads(EVIDENCE.read_text())
    assert list(evidence["surfaceMatrix"]) == ["telegramBot", "site", "miniApp", "admin", "api", "native"]
    assert evidence["surfaceMatrix"]["admin"]["mode"] == "OPERATOR_ONLY"
    assert evidence["surfaceMatrix"]["api"]["mode"] == "OPERATOR_ONLY"
    assert all(item["implementation"] == "NOT_IMPLEMENTED" for item in evidence["surfaceMatrix"].values())
    conclusion = evidence["coverageConclusion"]
    assert conclusion["sixSurfacesClassified"] is True and conclusion["deploymentAuthorityIdentified"] is True
    assert all(value is False for key, value in conclusion.items()
               if key not in {"sixSurfacesClassified", "deploymentAuthorityIdentified"})


def test_observation_did_not_exercise_deployment_authority():
    evidence = json.loads(EVIDENCE.read_text())
    for key in ("productionMutation", "gitFetchOrPullExecuted", "credentialValueRead",
                "deployScriptExecuted", "serviceRestarted", "unitOrTimerChanged"):
        assert evidence[key] is False
    assert evidence["acceptance"] == "PARTIAL_NOT_ACCEPTED"
    assert len(evidence["independentReviews"]) == 3
