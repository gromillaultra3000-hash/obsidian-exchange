import copy
import hashlib
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_hardened_executor_preflight import (  # noqa: E402
    POSTGRES_IMAGE, SCHEMA, STEPS, assess_hardened_executor_preflight,
    validate_executor_preflight_proof,
)
from core.e4_rehearsal_runner_plan import build_rehearsal_runner_plan  # noqa: E402


NOW = 1_800_000_000_000
MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def plan():
    return build_rehearsal_runner_plan(
        evidence_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())


def proof(value):
    return {
        "schemaVersion": SCHEMA,
        "planId": value["planId"],
        "evaluatedAtEpochMs": NOW + 1,
        "replayClaimBeforeFirstDockerEffect": True,
        "replayClaimId": "e4orr_" + "a" * 64,
        "target": {
            "targetRef": "e4-disposable-pg-20260822-02",
            "targetFingerprintSha256": "1" * 64,
            "absentBeforeStart": True,
            "ownershipTokenCaptured": True,
            "containerIdentityCaptured": True,
            "targetNameImmutable": True,
        },
        "container": {
            "image": POSTGRES_IMAGE,
            "network": "none",
            "readOnlyRoot": True,
            "publishedPorts": [],
            "persistentVolume": False,
            "tmpfsOnly": True,
            "noNewPrivileges": True,
            "dropAllCapabilities": True,
            "nonRoot": True,
            "boundedHealthcheck": True,
            "boundedShutdown": True,
            "noHostPath": True,
        },
        "snapshot": {
            "preExisting": True,
            "encrypted": True,
            "immutableAtHandoff": True,
            "digestVerified": True,
            "plaintextPersistenceNone": True,
            "productionDisconnected": True,
            "absentAfterTeardown": True,
        },
        "clock": {
            "attested": True,
            "issuerId": "trusted-clock-authority",
            "observedAtEpochMs": NOW,
            "expiresAtEpochMs": NOW + 900_000,
        },
        "production": {
            "contacted": False,
            "credentialsPresent": False,
            "writesPerformed": False,
            "networkRouteAllowed": False,
        },
        "teardown": {
            "targetDestroyed": True,
            "targetAbsentAfter": True,
            "snapshotDestroyed": True,
            "snapshotAbsentAfter": True,
            "ownershipReleased": True,
            "cleanupEvidenceCaptured": True,
        },
        "steps": [
            {"sequence": index, "stepId": step, "effect": effect,
             "completed": True, "evidenceCaptured": True}
            for index, (step, effect) in enumerate(STEPS, start=1)
        ],
        "authority": {
            "executionAuthorized": False,
            "productionDatabaseContactAllowed": False,
            "productionNetworkAllowed": False,
            "productionCredentialsAllowed": False,
            "proposalApplicationAllowed": False,
            "persistentTargetAllowed": False,
            "automaticRetryAllowed": False,
            "promotionAllowed": False,
            "actionAllowed": False,
            "moneyActionAllowed": False,
            "executionEffect": "NONE",
        },
    }


class E4HardenedExecutorPreflightTests(unittest.TestCase):
    def test_complete_mechanical_proof_never_becomes_execution_authority(self):
        value = plan()
        result = assess_hardened_executor_preflight(plan=value, proof=proof(value))
        self.assertEqual(result["status"], "MECHANICAL_PRECHECK_PASS_NON_AUTHORITATIVE")
        self.assertTrue(result["mechanicalPreflightPassed"])
        self.assertFalse(result["executionEligible"])
        self.assertFalse(result["actionAllowed"])
        self.assertIn("HARDENED_EXECUTOR_RUNTIME_NOT_PRESENT", result["blockers"])

    def test_invalid_proof_returns_no_go(self):
        value = plan()
        changed = copy.deepcopy(proof(value))
        changed["container"]["network"] = "host"
        result = assess_hardened_executor_preflight(plan=value, proof=changed)
        self.assertEqual(result["status"], "NO_GO")
        self.assertEqual(result["blockers"], ["PREFLIGHT_PROOF_INVALID"])
        self.assertFalse(result["executionEligible"])

    def test_security_landmines_fail_closed(self):
        value = plan()
        cases = (
            ("replayClaimBeforeFirstDockerEffect", False),
            ("target", {**proof(value)["target"], "ownershipTokenCaptured": False}),
            ("container", {**proof(value)["container"], "publishedPorts": [5432]}),
            ("snapshot", {**proof(value)["snapshot"], "preExisting": False}),
            ("clock", {**proof(value)["clock"], "attested": False}),
            ("production", {**proof(value)["production"], "contacted": True}),
            ("teardown", {**proof(value)["teardown"], "targetAbsentAfter": False}),
            ("steps", list(reversed(proof(value)["steps"]))),
            ("authority", {**proof(value)["authority"], "actionAllowed": True}),
        )
        for field, replacement in cases:
            with self.subTest(field=field):
                changed = copy.deepcopy(proof(value))
                changed[field] = replacement
                with self.assertRaises(ValueError):
                    validate_executor_preflight_proof(plan=value, proof=changed)


if __name__ == "__main__":
    unittest.main()
