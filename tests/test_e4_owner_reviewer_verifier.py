import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_owner_reviewer_verifier import (  # noqa: E402
    verify_owner_reviewer_artifacts,
)


HANDOFF = ROOT / "E4-owner-handoff"


def verify(*, now: int, root: Path = HANDOFF):
    return verify_owner_reviewer_artifacts(
        registry_path=root / "e4-owner-reviewer-trust-anchor-and-binding-candidate.v3.json",
        payload_path=root / "e4-owner-decision-payload.v4.json",
        owner_signature_path=root / "e4-owner-decision-payload.v4.json.sig",
        owner_public_key_path=root / "owner-signing-v2.pub",
        envelope_path=root / "e4-reviewer-review-envelope.v3.json",
        reviewer_signature_path=root / "e4-reviewer-review-envelope.v3.json.sig",
        reviewer_public_key_path=root / "reviewer-signing-v2.pub",
        evaluated_at_epoch_ms=now,
    )


class E4OwnerReviewerVerifierTests(unittest.TestCase):
    def test_real_handoff_verifies_but_stays_no_go(self):
        payload = json.loads(
            (HANDOFF / "e4-owner-decision-payload.v4.json").read_text())
        result = verify(now=payload["approval"]["approvedAtEpochMs"] + 1)
        self.assertTrue(result["ownerSignatureVerified"])
        self.assertTrue(result["reviewerSignatureVerified"])
        self.assertTrue(result["exactBindingVerified"])
        self.assertTrue(result["freshnessVerified"])
        self.assertEqual(result["registryStatus"], "CANDIDATE_NOT_AUTHORIZED")
        self.assertEqual(result["status"], "NO_GO")
        self.assertIn("TRUST_REGISTRY_NOT_AUTHENTICATED", result["blockers"])
        self.assertIn("HARDENED_EXECUTOR_NOT_AVAILABLE", result["blockers"])
        self.assertFalse(result["executionAuthorized"])
        self.assertFalse(result["actionAllowed"])

    def test_expired_or_future_clock_is_fail_closed(self):
        payload = json.loads(
            (HANDOFF / "e4-owner-decision-payload.v4.json").read_text())
        expired = verify(now=payload["approval"]["expiresAtEpochMs"] + 1)
        self.assertFalse(expired["freshnessVerified"])
        self.assertIn("OWNER_WINDOW_NOT_CURRENT", expired["blockers"])
        future = verify(now=payload["approval"]["approvedAtEpochMs"] - 1002)
        self.assertFalse(future["freshnessVerified"])
        self.assertIn("OWNER_WINDOW_NOT_CURRENT", future["blockers"])

    def test_exact_binding_tamper_is_rejected_before_signature_result(self):
        payload = json.loads(
            (HANDOFF / "e4-owner-decision-payload.v4.json").read_text())
        with tempfile.TemporaryDirectory(prefix="e4-verifier-test-") as raw:
            root = Path(raw)
            for name in (
                "e4-owner-reviewer-trust-anchor-and-binding-candidate.v3.json",
                "e4-owner-decision-payload.v4.json",
                "e4-owner-decision-payload.v4.json.sig",
                "owner-signing-v2.pub",
                "e4-reviewer-review-envelope.v3.json",
                "e4-reviewer-review-envelope.v3.json.sig",
                "reviewer-signing-v2.pub",
            ):
                (root / name).write_bytes((HANDOFF / name).read_bytes())
            payload["approval"]["targetRef"] = "different-target"
            (root / "e4-owner-decision-payload.v4.json").write_text(
                json.dumps(payload, indent=2) + "\n")
            result = verify(
                now=payload["approval"]["approvedAtEpochMs"] + 1,
                root=root)
        self.assertEqual(result["status"], "NO_GO")
        self.assertIn("ARTIFACT_INVALID", result["blockers"])
        self.assertFalse(result["exactBindingVerified"])


if __name__ == "__main__":
    unittest.main()
