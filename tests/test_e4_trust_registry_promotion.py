import copy
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_trust_registry_promotion import (  # noqa: E402
    PromotionVerificationError,
    verify_authenticated_promotion,
)


HANDOFF = ROOT / "E4-owner-handoff"
NOW = 1787440678816


def verify(**overrides):
    args = {
        "promotion_path": HANDOFF / "e4-trust-registry-promotion-payload.v1.json",
        "promotion_signature_path": HANDOFF / "e4-trust-registry-promotion-payload.v1.json.sig",
        "trust_root_public_key_path": HANDOFF / "e4-trust-root.pub",
        "registry_path": HANDOFF / "e4-owner-reviewer-trust-anchor-and-binding-candidate.v4.json",
        "payload_path": HANDOFF / "e4-owner-decision-payload.v5.json",
        "owner_signature_path": HANDOFF / "e4-owner-decision-payload.v5.json.sig",
        "owner_public_key_path": HANDOFF / "owner-signing-v2.pub",
        "envelope_path": HANDOFF / "e4-reviewer-review-envelope.v4.json",
        "reviewer_signature_path": HANDOFF / "e4-reviewer-review-envelope.v4.json.sig",
        "reviewer_public_key_path": HANDOFF / "reviewer-signing-v2.pub",
        "timestamp_evidence_path": HANDOFF / "e4-owner-decision-payload.v5.json.sig.digicert-rfc3161-evidence.v1.json",
        "timestamp_request_path": HANDOFF / "e4-owner-decision-payload.v5.json.sig.tsq",
        "timestamp_response_path": HANDOFF / "e4-owner-decision-payload.v5.json.sig.tsr",
        "timestamp_root_path": HANDOFF / "DigiCertAssuredIDRootCA.crt.pem",
        "timestamp_intermediate_path": HANDOFF / "DigiCertTrustedG4TimeStampingRSA4096SHA2562025CA1.pem",
        "evaluated_at_epoch_ms": NOW,
    }
    args.update(overrides)
    return verify_authenticated_promotion(**args)


class E4TrustRegistryPromotionTests(unittest.TestCase):
    def test_exact_promotion_is_authenticated_but_non_executing(self):
        result = verify()
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["registryStatus"], "AUTHENTICATED_ACTIVE")
        self.assertTrue(result["ownerSignatureVerified"])
        self.assertTrue(result["reviewerSignatureVerified"])
        self.assertTrue(result["trustedClockAttested"])
        self.assertTrue(result["replayEligible"])
        self.assertFalse(result["replayRegistryChecked"])
        self.assertFalse(result["executionAuthorized"])
        self.assertFalse(result["actionAllowed"])

    def test_tampered_promotion_signature_fails(self):
        with tempfile.TemporaryDirectory(prefix="e4-promotion-test-") as raw:
            root = Path(raw)
            promotion = json.loads((HANDOFF / "e4-trust-registry-promotion-payload.v1.json").read_text())
            promotion["promotion"]["requestedStatus"] = "ACTIVE_EXECUTION"
            promotion_path = root / "promotion.json"
            promotion_path.write_text(json.dumps(promotion, indent=2) + "\n")
            with self.assertRaises(PromotionVerificationError):
                verify(promotion_path=promotion_path)

    def test_tampered_timestamp_response_fails(self):
        with tempfile.TemporaryDirectory(prefix="e4-promotion-test-") as raw:
            response_path = Path(raw) / "response.tsr"
            shutil.copy2(HANDOFF / "e4-owner-decision-payload.v5.json.sig.tsr", response_path)
            data = bytearray(response_path.read_bytes())
            data[-1] ^= 1
            response_path.write_bytes(data)
            with self.assertRaises(PromotionVerificationError):
                verify(timestamp_response_path=response_path)


if __name__ == "__main__":
    unittest.main()
