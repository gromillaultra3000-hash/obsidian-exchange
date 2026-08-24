import copy
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e5_readiness import (
    CURRENT_OPERATIONAL_PROBES, OPERATIONAL_CHECKS, assess_e5_readiness,
    validate_e5_readiness,
)
from test_e5_recovery_rehearsal_result import fixture


def inputs(probes=None, **failed_steps):
    args, result = fixture(**failed_steps)
    return dict(
        result=result, authorization=args["authorization"], review=args["review"],
        proposal=args["proposal"], attempt=args["attempt"], policy=args["policy"],
        boundary=args["boundary"], consumption=args["consumption"],
        observations=args["observations"],
        consumed_authorization_ids=args["consumed_authorization_ids"],
        operational_probes=probes if probes is not None else CURRENT_OPERATIONAL_PROBES)


def test_current_truthful_proof_is_no_go_with_complete_synthetic_foundation():
    args = inputs()
    proof = assess_e5_readiness(**args)
    assert proof["status"] == "NO_GO" and proof["ready"] is False
    assert proof["stage"] == "DESIGN_AND_SYNTHETIC_FOUNDATION_COMPLETE"
    assert proof["blockers"] == list(OPERATIONAL_CHECKS)
    assert proof["selectedMobileStack"] == "UNDECIDED"
    assert proof["selectedProductionNetwork"] == "UNDECIDED"
    assert validate_e5_readiness(proof, **{
        key: value for key, value in args.items() if key != "operational_probes"}) == proof


def test_failed_synthetic_rehearsal_keeps_foundation_incomplete():
    proof = assess_e5_readiness(**inputs(NO_PRODUCTION_NETWORK="FAIL"))
    assert proof["status"] == "NO_GO"
    assert proof["stage"] == "FOUNDATION_INCOMPLETE"
    assert "SYNTHETIC_REHEARSAL_RESULT_PASSED" in proof["blockers"]


@pytest.mark.parametrize("missing", OPERATIONAL_CHECKS)
def test_each_operational_prerequisite_independently_blocks(missing):
    probes = {name: True for name in OPERATIONAL_CHECKS}
    probes[missing] = False
    proof = assess_e5_readiness(**inputs(probes))
    assert proof["status"] == "NO_GO" and proof["blockers"] == [missing]


def test_synthetic_all_true_is_review_eligible_but_never_enables_runtime():
    proof = assess_e5_readiness(**inputs({name: True for name in OPERATIONAL_CHECKS}))
    assert proof["status"] == "GO" and proof["ready"] is True
    assert proof["eligibleForNativeImplementationReview"] is True
    for field in (
        "productionReleaseAllowed", "recoveryExecutionAllowed",
        "authorityInstallationAllowed", "signingAllowed", "runtimeEnableAllowed",
        "actionAllowed",
    ):
        assert proof[field] is False
    assert proof["executionEffect"] == "NONE"


def test_probe_schema_is_exact_and_boolean():
    with pytest.raises(ValueError):
        assess_e5_readiness(**inputs({}))
    probes = dict(CURRENT_OPERATIONAL_PROBES); probes[OPERATIONAL_CHECKS[0]] = 1
    with pytest.raises(ValueError):
        assess_e5_readiness(**inputs(probes))


def test_readiness_capability_or_verdict_tamper_fails():
    args = inputs(); proof = assess_e5_readiness(**args)
    validation = {key: value for key, value in args.items() if key != "operational_probes"}
    for field, replacement in (
        ("status", "GO"), ("ready", True),
        ("eligibleForNativeImplementationReview", True),
        ("selectedMobileStack", "ios"), ("selectedProductionNetwork", "mainnet"),
        ("productionReleaseAllowed", True), ("recoveryExecutionAllowed", True),
        ("authorityInstallationAllowed", True), ("signingAllowed", True),
        ("runtimeEnableAllowed", True), ("executionEffect", "ENABLE"),
        ("actionAllowed", True),
    ):
        changed = copy.deepcopy(proof); changed[field] = replacement
        with pytest.raises(ValueError):
            validate_e5_readiness(changed, **validation)


def test_contract_has_no_probe_runtime_storage_network_sdk_or_secret_surface():
    source = (ROOT / "relay/core/e5_readiness.py").read_text().lower()
    for forbidden in (
        "open(", "read_text", "read_bytes", "sqlite", "psycopg", "requests",
        "httpx", "aiohttp", "socket", "os.environ", "subprocess", "docker",
        "systemctl", "mnemonic", "private_key", "seed_phrase", "keychain",
        "keystore", "android", "ios", "sign_transaction", "time.time",
    ):
        assert forbidden not in source
