import copy
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "kairos"))

from app.e3_testnet_capabilities import (
    FORBIDDEN_PERMISSIONS, REQUIRED_PERMISSIONS,
    assess_restricted_testnet_account, build_testnet_capability_observation,
    validate_restricted_testnet_account, validate_testnet_capability_observation,
)

NOW = 1786420801000


def observation(kind, *, outcome=None, granted=None, denied=None, observed=NOW):
    values = dict(
        observation_type=kind, provider="bybit", account_ref="sandbox_1",
        observed_at_epoch_ms=observed, expires_at_epoch_ms=observed + 900_000,
        source_evidence_hash={"PERMISSION_INVENTORY": "a", "WITHDRAWAL_DENIAL": "b",
                              "TRANSFER_DENIAL": "c"}[kind] * 64)
    if kind == "PERMISSION_INVENTORY":
        values.update(outcome=outcome or "OBSERVED",
                      granted_permissions=sorted(REQUIRED_PERMISSIONS) if granted is None else granted,
                      denied_permissions=sorted(FORBIDDEN_PERMISSIONS) if denied is None else denied)
    else:
        values.update(outcome=outcome or "DENIED",
                      denial_code="PERMISSION_DENIED" if (outcome or "DENIED") == "DENIED" else "NONE")
    return build_testnet_capability_observation(**values)


def complete(**changes):
    values = {
        "PERMISSION_INVENTORY": observation("PERMISSION_INVENTORY"),
        "WITHDRAWAL_DENIAL": observation("WITHDRAWAL_DENIAL"),
        "TRANSFER_DENIAL": observation("TRANSFER_DENIAL"),
    }
    values.update(changes)
    return list(values.values())


def test_secret_free_restricted_testnet_evidence_is_offline_candidate_only():
    evidence = assess_restricted_testnet_account(complete(), assessed_at_epoch_ms=NOW + 1)
    assert evidence["status"] == "OFFLINE_ELIGIBLE"
    assert evidence["offlineEligible"] is True
    assert evidence["runtimeVerified"] is False
    assert evidence["readinessCheckSatisfied"] is False
    assert evidence["containsSecrets"] is False
    assert evidence["actionAllowed"] is False
    assert validate_restricted_testnet_account(json.loads(json.dumps(evidence))) == evidence
    assert all(validate_testnet_capability_observation(item) == item
               for item in evidence["observations"])


@pytest.mark.parametrize("replacement,blocker", [
    (observation("PERMISSION_INVENTORY", granted=["BALANCE_READ"]), "REQUIRED_SPOT_SCOPE"),
    (observation("PERMISSION_INVENTORY", granted=sorted(REQUIRED_PERMISSIONS | {"WITHDRAWAL"}),
                 denied=sorted(FORBIDDEN_PERMISSIONS - {"WITHDRAWAL"})), "NO_FORBIDDEN_GRANTS"),
    (observation("PERMISSION_INVENTORY", denied=[]), "FORBIDDEN_SCOPE_EXPLICITLY_DENIED"),
    (observation("WITHDRAWAL_DENIAL", outcome="ALLOWED"), "WITHDRAWAL_DENIED"),
    (observation("TRANSFER_DENIAL", outcome="ALLOWED"), "TRANSFER_DENIED"),
])
def test_permission_or_denial_drift_is_explicit_no_go(replacement, blocker):
    evidence = assess_restricted_testnet_account(
        complete(**{replacement["observationType"]: replacement}),
        assessed_at_epoch_ms=NOW + 1)
    assert evidence["status"] == "NO_GO"
    assert blocker in evidence["blockers"]
    assert evidence["readinessCheckSatisfied"] is False


def test_stale_future_mixed_or_incomplete_observations_fail_closed():
    stale = assess_restricted_testnet_account(complete(), assessed_at_epoch_ms=NOW + 900_001)
    assert stale["blockers"] == ["EVIDENCE_FRESH"]
    future = [observation(kind, observed=NOW + 1002) for kind in
              ("PERMISSION_INVENTORY", "WITHDRAWAL_DENIAL", "TRANSFER_DENIAL")]
    assert assess_restricted_testnet_account(future, assessed_at_epoch_ms=NOW)["status"] == "NO_GO"
    with pytest.raises(ValueError):
        assess_restricted_testnet_account(complete()[:2], assessed_at_epoch_ms=NOW)
    mixed = complete()
    mixed[0] = copy.deepcopy(mixed[0])
    mixed[0]["accountRef"] = "sandbox_2"
    with pytest.raises(ValueError):
        assess_restricted_testnet_account(mixed, assessed_at_epoch_ms=NOW)


@pytest.mark.parametrize("field,value", [
    ("containsSecrets", True), ("environment", "MAINNET"),
    ("accountMode", "LIVE"), ("observationId", "tco_" + "0" * 64),
])
def test_observation_tamper_or_live_secret_surface_is_rejected(field, value):
    changed = observation("PERMISSION_INVENTORY")
    changed[field] = value
    with pytest.raises(ValueError):
        validate_testnet_capability_observation(changed)


def test_evidence_tamper_cannot_claim_runtime_readiness():
    evidence = assess_restricted_testnet_account(complete(), assessed_at_epoch_ms=NOW + 1)
    for field, value in (("runtimeVerified", True), ("readinessCheckSatisfied", True),
                         ("actionAllowed", True), ("evidenceId", "rta_" + "0" * 64)):
        changed = copy.deepcopy(evidence)
        changed[field] = value
        with pytest.raises(ValueError):
            validate_restricted_testnet_account(changed)


def test_contract_has_no_secret_network_clock_or_runtime_configuration_surface():
    source = (ROOT / "kairos/app/e3_testnet_capabilities.py").read_text()
    for forbidden in ("apiKey", "apiSecret", "credential", "requests", "httpx",
                      "aiohttp", "socket", "ccxt", "os.environ", "time.time"):
        assert forbidden not in source
