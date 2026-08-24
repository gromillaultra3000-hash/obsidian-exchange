import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_authoritative_gate_callbacks import (  # noqa: E402
    E4AuthoritativeGateCallbacks,
)
from core.e4_authenticated_gate_provider import (  # noqa: E402
    GateProviderError, validate_gate_provider_result,
)
from core.e4_hardened_executor import (  # noqa: E402
    validate_authenticated_execution_gate,
)
from core.e4_owner_reviewer_replay_registry import (  # noqa: E402
    SQLiteE4OwnerReviewerReplayRegistry,
)
from core.e4_rehearsal_receipt_consumption import (  # noqa: E402
    SQLiteE4RehearsalReceiptLedger,
)

from test_e4_hardened_executor import (  # noqa: E402
    KEY_REF, NOW, SNAPSHOT_REF, fixture,
)


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


class E4AuthoritativeGateCallbacksTests(unittest.TestCase):
    def _paths(self, directory: Path, values):
        plan, approval, _receipt, _boundary, _authenticated, _consumption = values
        promotion = directory / "promotion.json"
        payload = directory / "owner-payload.json"
        envelope = directory / "review-envelope.json"
        promotion_value = {
            "frozenBinding": {
                "planId": plan["planId"], "targetRef": approval["targetRef"],
                "targetFingerprintSha256": approval["targetFingerprintSha256"],
                "snapshotSha256": approval["snapshotSha256"],
                "keyRefSha256": approval["keyRefSha256"],
                "scope": approval["scope"], "invocationLimit": 1,
            },
            "boundEvidence": {
                "ownerPayloadSha256": "1" * 64,
                "ownerSignatureSha256": "2" * 64,
                "reviewerEnvelopeSha256": "3" * 64,
                "reviewerSignatureSha256": "4" * 64,
                "timestampEvidenceSha256": "5" * 64,
            },
        }
        payload_value = {
            "payloadId": "payload-1",
            "approval": {
                field: approval[field] for field in (
                    "planId", "targetRef", "targetFingerprintSha256",
                    "snapshotSha256", "snapshotRefSha256", "keyRefSha256",
                    "approvedAtEpochMs", "expiresAtEpochMs", "scope",
                    "invocationLimit",
                )
            },
        }
        envelope_value = {"envelopeId": "envelope-1"}
        promotion.write_text(json.dumps(promotion_value), encoding="utf-8")
        payload.write_text(json.dumps(payload_value), encoding="utf-8")
        envelope.write_text(json.dumps(envelope_value), encoding="utf-8")
        return promotion, payload, envelope

    def _provider(self, directory: Path, values, events):
        plan, approval, _receipt, _boundary, _authenticated, _consumption = values
        promotion, payload, envelope = self._paths(directory, values)
        verified = {
            "schemaVersion": "e4-owner-reviewer-verification-result.v1",
            "status": "VERIFIED", "evaluatedAtEpochMs": NOW + 2,
            "ownerSignatureVerified": True, "reviewerSignatureVerified": True,
            "exactBindingVerified": True, "freshnessVerified": True,
            "registryStatus": "AUTHENTICATED_ACTIVE",
            "trustedClockAttested": True, "replayEligible": True,
            "executionAuthorized": False, "actionAllowed": False,
            "verificationId": "e4ovr_" + "a" * 64,
            "promotionPayloadSha256": hashlib.sha256(
                promotion.read_bytes()).hexdigest(),
            "timestampGenTimeUtc": "2026-08-23T00:00:00Z",
        }

        def verify(**kwargs):
            events.append("verify")
            return verified

        replay = SQLiteE4OwnerReviewerReplayRegistry(str(directory / "replay.db"))
        receipt = SQLiteE4RehearsalReceiptLedger(str(directory / "receipt.db"))

        class RecordingReplay:
            def claim(self, **kwargs):
                events.append("claim")
                return replay.claim(**kwargs)

        class RecordingReceipt:
            def consume(self, **kwargs):
                events.append("consume")
                return receipt.consume(**kwargs)

        return E4AuthoritativeGateCallbacks(
            promotion_path=promotion, promotion_signature_path=directory / "missing-1",
            trust_root_public_key_path=directory / "missing-2",
            registry_path=directory / "missing-3", payload_path=payload,
            owner_signature_path=directory / "missing-4",
            owner_public_key_path=directory / "missing-5", envelope_path=envelope,
            reviewer_signature_path=directory / "missing-6",
            reviewer_public_key_path=directory / "missing-7",
            timestamp_evidence_path=directory / "missing-8",
            timestamp_request_path=directory / "missing-9",
            timestamp_response_path=directory / "missing-10",
            timestamp_root_path=directory / "missing-11",
            timestamp_intermediate_path=directory / "missing-12",
            replay_registry=RecordingReplay(), receipt_ledger=RecordingReceipt(),
            promotion_verifier=verify,
        )

    def test_real_temporary_ledgers_are_wired_in_verifier_claim_receipt_order(self):
        values = fixture()
        with tempfile.TemporaryDirectory(prefix="e4-authoritative-callback-test-") as raw:
            events = []
            provider = self._provider(Path(raw), values, events)
            result = provider.acquire(
                plan=values[0], owner_approval=values[1], receipt=values[2],
                boundary=values[3], snapshot_ref=SNAPSHOT_REF, key_ref=KEY_REF,
                evaluated_at_epoch_ms=NOW + 2)
            self.assertEqual(events, ["verify", "claim", "consume"])
            validate_gate_provider_result(
                result, plan=values[0], receipt=values[2], boundary=values[3],
                snapshot_ref=SNAPSHOT_REF, key_ref=KEY_REF)
            authenticated = result["authenticatedEvidence"]
            consumption = result["replayConsumption"]
            self.assertEqual(
                validate_authenticated_execution_gate(
                    authenticated_evidence=authenticated,
                    replay_consumption=consumption)["registryStatus"],
                "AUTHENTICATED_ACTIVE")
            self.assertEqual(consumption["replayClaimId"],
                             authenticated["replay"]["claimId"])

    def test_constructor_is_lazy_and_does_not_read_or_claim(self):
        values = fixture()

        class EmptyReplay:
            def claim(self, **kwargs):
                raise AssertionError("claim must not occur during construction")

        class EmptyReceipt:
            def consume(self, **kwargs):
                raise AssertionError("consume must not occur during construction")

        with tempfile.TemporaryDirectory(prefix="e4-authoritative-lazy-test-") as raw:
            directory = Path(raw)
            provider = E4AuthoritativeGateCallbacks(
                promotion_path=directory / "does-not-exist",
                promotion_signature_path=directory / "does-not-exist-2",
                trust_root_public_key_path=directory / "does-not-exist-3",
                registry_path=directory / "does-not-exist-4",
                payload_path=directory / "does-not-exist-5",
                owner_signature_path=directory / "does-not-exist-6",
                owner_public_key_path=directory / "does-not-exist-7",
                envelope_path=directory / "does-not-exist-8",
                reviewer_signature_path=directory / "does-not-exist-9",
                reviewer_public_key_path=directory / "does-not-exist-10",
                timestamp_evidence_path=directory / "does-not-exist-11",
                timestamp_request_path=directory / "does-not-exist-12",
                timestamp_response_path=directory / "does-not-exist-13",
                timestamp_root_path=directory / "does-not-exist-14",
                timestamp_intermediate_path=directory / "does-not-exist-15",
                replay_registry=EmptyReplay(), receipt_ledger=EmptyReceipt(),
                promotion_verifier=lambda **kwargs: values[4],
            )
            self.assertIsNotNone(provider)

    def test_promotion_binding_mismatch_stops_before_one_shot_claim(self):
        values = fixture()
        with tempfile.TemporaryDirectory(prefix="e4-authoritative-binding-test-") as raw:
            events = []
            provider = self._provider(Path(raw), values, events)
            promotion = Path(raw) / "promotion.json"
            value = json.loads(promotion.read_text())
            value["frozenBinding"]["targetRef"] = "different-target"
            promotion.write_text(json.dumps(value), encoding="utf-8")
            with self.assertRaises(GateProviderError):
                provider.acquire(
                    plan=values[0], owner_approval=values[1], receipt=values[2],
                    boundary=values[3], snapshot_ref=SNAPSHOT_REF, key_ref=KEY_REF,
                    evaluated_at_epoch_ms=NOW + 2)
            self.assertEqual(events, ["verify"])


if __name__ == "__main__":
    unittest.main()
