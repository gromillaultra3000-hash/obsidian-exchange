import copy
import inspect
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT / "kairos", ROOT / "lumi", ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.shadow_mutual_auth import validate_transcript
from lumi.app.integration.shadow_preflight_proof import (
    build_preflight_proof, validate_preflight_proof,
)
from lumi.app.integration.shadow_transport_readiness import CHECKS, assess_readiness


def fixture(name):
    return json.loads((ROOT / f"contracts/e2-shadow/{name}").read_text())


def all_ready(**changes):
    probes = {"schemaVersion": "shadow-transport-probes.v1"}
    probes.update({field: True for _, field, _ in CHECKS})
    probes.update(changes)
    return assess_readiness(probes)


def test_frozen_production_no_go_proof_is_exact_and_non_executing():
    result = build_preflight_proof(
        fixture("transport-readiness-replay-ready-no-go.v1.json"),
        fixture("mutual-auth-transcript.v1.json"),
        validate_self_test=validate_transcript)
    assert result == fixture("preflight-proof-no-go.v1.json")
    assert validate_preflight_proof(result) == result
    assert result["status"] == "INELIGIBLE" and result["eligible"] is False
    assert len(result["blockers"]) == 5 and result["selfTestPassed"] is True
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False


def test_synthetic_go_is_eligible_but_never_authorizes_action():
    result = build_preflight_proof(
        all_ready(), fixture("mutual-auth-transcript.v1.json"),
        validate_self_test=validate_transcript)
    assert result["status"] == "ELIGIBLE" and result["eligible"] is True
    assert result["blockers"] == [] and result["selfTestPassed"] is True
    assert result["executionEffect"] == "NONE" and result["actionAllowed"] is False


@pytest.mark.parametrize(("field", "blocker"), [
    (field, blocker) for _, field, blocker in CHECKS
])
def test_each_readiness_blocker_keeps_preflight_ineligible(field, blocker):
    changes = {field: False}
    if field == "keyringConfigured":
        changes.update(keyringValid=False, activeKeyAvailable=False)
    elif field == "keyringValid":
        changes.update(activeKeyAvailable=False)
    elif field == "replayPathConfigured":
        changes.update(replayParentSafe=False, replayStateValid=False)
    elif field == "replayParentSafe":
        changes.update(replayStateValid=False)
    result = build_preflight_proof(
        all_ready(**changes), fixture("mutual-auth-transcript.v1.json"),
        validate_self_test=validate_transcript)
    assert result["status"] == "INELIGIBLE" and blocker in result["blockers"]
    assert result["actionAllowed"] is False


def test_invalid_self_test_fails_closed_instead_of_emitting_eligibility():
    transcript = fixture("mutual-auth-transcript.v1.json")
    transcript["dispatch"]["actionAllowed"] = True
    with pytest.raises(ValueError, match="self-test failed"):
        build_preflight_proof(
            all_ready(), transcript, validate_self_test=validate_transcript)


@pytest.mark.parametrize(("path", "value"), [
    (("proofId",), "pf_" + "0" * 64),
    (("status",), "ELIGIBLE"),
    (("eligible",), True),
    (("blockers",), []),
    (("selfTestPassed",), False),
    (("selfTest", "requestHash"), "0" * 64),
    (("selfTest", "actionAllowed"), True),
    (("readiness", "actionAllowed"), True),
    (("actionAllowed",), True),
])
def test_preflight_proof_tamper_fails_closed(path, value):
    proof = build_preflight_proof(
        fixture("transport-readiness-replay-ready-no-go.v1.json"),
        fixture("mutual-auth-transcript.v1.json"),
        validate_self_test=validate_transcript)
    target = proof
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value
    with pytest.raises(ValueError):
        validate_preflight_proof(proof)


def test_module_has_no_env_file_network_route_state_or_crypto_surface():
    source = inspect.getsource(sys.modules[
        "lumi.app.integration.shadow_preflight_proof"]).lower()
    assert all(term not in source for term in (
        "requests", "urllib", "http://", "https://", "socket", "os.getenv",
        "environ", "open(", "pathlib", "fastapi", "router", "cryptography",
        "write", "append("))
