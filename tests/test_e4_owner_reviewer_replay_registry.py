import copy
import hashlib
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_owner_reviewer_replay_registry import (  # noqa: E402
    SQLiteE4OwnerReviewerReplayRegistry, build_claim_record,
    validate_claim_record,
)


NOW = 1_800_000_000_000


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def verified_result():
    return {
        "schemaVersion": "e4-owner-reviewer-verification-result.v1",
        "verificationId": "e4ovr_" + "a" * 64,
        "evaluatedAtEpochMs": NOW,
        "ownerSignatureVerified": True,
        "reviewerSignatureVerified": True,
        "exactBindingVerified": True,
        "freshnessVerified": True,
        "registryStatus": "AUTHENTICATED_ACTIVE",
        "trustedClockAttested": True,
        "replayEligible": True,
        "status": "VERIFIED",
        "executionAuthorized": False,
        "actionAllowed": False,
    }


def claim(registry, *, payload="payload_1", envelope="envelope_1",
          artifact="artifact_1", result=None, claimed=NOW + 1):
    return registry.claim(
        verification_result=result or verified_result(), payload_id=payload,
        envelope_id=envelope, artifact_digest=digest(artifact),
        claimed_at_epoch_ms=claimed)


class E4OwnerReviewerReplayRegistryTests(unittest.TestCase):
    def test_one_shot_replay_and_conflict_are_blocked(self):
        with tempfile.TemporaryDirectory(prefix="e4-replay-test-") as raw:
            registry = SQLiteE4OwnerReviewerReplayRegistry(str(Path(raw) / "ledger.db"))
            first = claim(registry)
            self.assertEqual(first["status"], "CONSUMED")
            second = claim(registry)
            self.assertEqual(second["status"], "REPLAY_BLOCKED")
            self.assertEqual(second["claimId"], first["claimId"])
            conflict = claim(registry, envelope="envelope_2")
            self.assertEqual(conflict["status"], "CONFLICT_BLOCKED")
            self.assertFalse(conflict["replayClaimAllowed"])

    def test_concurrent_exact_claims_have_one_winner(self):
        with tempfile.TemporaryDirectory(prefix="e4-replay-test-") as raw:
            registry = SQLiteE4OwnerReviewerReplayRegistry(str(Path(raw) / "ledger.db"))
            results, errors = [], []

            def run():
                try:
                    results.append(claim(registry))
                except Exception as exc:  # pragma: no cover - diagnostic assertion
                    errors.append(exc)

            threads = [threading.Thread(target=run) for _ in range(2)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertEqual(errors, [])
            self.assertEqual(sorted(item["status"] for item in results),
                             ["CONSUMED", "REPLAY_BLOCKED"])

    def test_fault_boundaries_preserve_or_block_claim(self):
        def fail():
            raise RuntimeError("injected")

        with tempfile.TemporaryDirectory(prefix="e4-replay-test-") as raw:
            path = str(Path(raw) / "before.db")
            before = SQLiteE4OwnerReviewerReplayRegistry(
                path, fault_before_commit=fail)
            with self.assertRaises(RuntimeError):
                claim(before)
            self.assertEqual(claim(SQLiteE4OwnerReviewerReplayRegistry(path))["status"],
                             "CONSUMED")

            after_path = str(Path(raw) / "after.db")
            after = SQLiteE4OwnerReviewerReplayRegistry(
                after_path, fault_after_commit=fail)
            with self.assertRaises(RuntimeError):
                claim(after)
            retry = SQLiteE4OwnerReviewerReplayRegistry(after_path)
            self.assertEqual(claim(retry)["status"], "REPLAY_BLOCKED")

    def test_no_go_verifier_result_cannot_claim(self):
        result = verified_result()
        result["replayEligible"] = False
        result["status"] = "NO_GO"
        with tempfile.TemporaryDirectory(prefix="e4-replay-test-") as raw:
            registry = SQLiteE4OwnerReviewerReplayRegistry(str(Path(raw) / "ledger.db"))
            with self.assertRaises(ValueError):
                claim(registry, result=result)

    def test_claim_record_is_closed_and_tamper_evident(self):
        record = build_claim_record(
            payload_id="payload_1", envelope_id="envelope_1",
            artifact_digest=digest("artifact_1"), verification_id="e4ovr_" + "a" * 64,
            claimed_at_epoch_ms=NOW + 1)
        self.assertEqual(validate_claim_record(record), record)
        changed = copy.deepcopy(record)
        changed["actionAllowed"] = True
        with self.assertRaises(ValueError):
            validate_claim_record(changed)

    def test_path_is_explicitly_temporary(self):
        with self.assertRaises(ValueError):
            SQLiteE4OwnerReviewerReplayRegistry("/root/production-replay.db")


if __name__ == "__main__":
    unittest.main()
