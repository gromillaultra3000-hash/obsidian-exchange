import base64
import importlib.util
import json
import sys
import sqlite3
import tempfile
import time
import unittest
from pathlib import Path


ROOT = Path("/root")
HANDOFF = ROOT / "E4-owner-handoff"
sys.path.insert(0, str(ROOT / "relay"))

from core import e4_owner_one_shot_server as server  # noqa: E402
from core.e4_atomic_one_shot_ledger import AtomicE4OneShotLedger  # noqa: E402
from test_e4_hardened_executor import (  # noqa: E402
    KEY_REF, NOW, SNAPSHOT_REF, fixture,
)


def load_termux_helper():
    path = HANDOFF / "e4_one_shot_termux.py"
    spec = importlib.util.spec_from_file_location("e4_one_shot_termux", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.PUBLIC_KEYS = {
        "OWNER": HANDOFF / "owner-signing-v2.pub",
        "REVIEWER": HANDOFF / "reviewer-signing-v2.pub",
        "TRUST_ROOT": HANDOFF / "e4-trust-root.pub",
    }
    return module


class E4OwnerOneShotTest(unittest.TestCase):
    def setUp(self):
        self.termux = load_termux_helper()

    def test_legacy_authenticated_payload_without_release_is_rejected(self):
        payload = (HANDOFF / "e4-owner-decision-payload.v11.json").read_bytes()
        with self.assertRaisesRegex(
                self.termux.HandoffError, "owner payload shape is invalid"):
            self.termux._validate_payload(payload)

    def test_local_payload_tamper_is_rejected(self):
        with tempfile.TemporaryDirectory(prefix="e4-one-shot-test-") as directory:
            _path, raw, _payload = server._fresh_payload(
                Path(directory), time.time_ns() // 1_000_000)
        value = json.loads(raw)
        value["approval"]["snapshotSha256"] = "0" * 64
        with self.assertRaises(self.termux.HandoffError):
            self.termux._validate_payload(json.dumps(value).encode())

    def test_payload_rejects_termux_release_digest_drift(self):
        with tempfile.TemporaryDirectory(prefix="e4-one-shot-test-") as directory:
            _path, raw, _payload = server._fresh_payload(
                Path(directory), time.time_ns() // 1_000_000)
        value = json.loads(raw)
        value["executionRelease"]["files"][
            "E4-owner-handoff/e4_one_shot_termux.py"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(
                self.termux.HandoffError, "does not bind this Termux helper"):
            self.termux._validate_payload(json.dumps(value).encode())

    def test_fresh_builder_keeps_authority_false_and_exact_window(self):
        with tempfile.TemporaryDirectory(prefix="e4-one-shot-test-") as directory:
            approved = time.time_ns() // 1_000_000
            path, raw, payload = server._fresh_payload(Path(directory), approved)
            self.assertEqual(path.name, "e4-owner-decision-payload.json")
            self.assertEqual(
                payload["approval"]["expiresAtEpochMs"] - approved,
                15 * 60 * 1000)
            self.assertTrue(all(
                item is False for item in payload["authority"].values()
                if isinstance(item, bool)))
            self.assertEqual(server._sha_bytes(raw), server._sha_bytes(path.read_bytes()))

    def test_dynamic_review_and_promotion_have_no_stale_refs(self):
        with tempfile.TemporaryDirectory(prefix="e4-one-shot-test-") as directory:
            root = Path(directory)
            approved = time.time_ns() // 1_000_000
            payload_path, payload_raw, payload = server._fresh_payload(root, approved)
            owner_signature = b"public-owner-signature-fixture"
            owner_signature_path = root / "e4-owner-decision-payload.json.sig"
            server._write_new(owner_signature_path, owner_signature)
            evidence_path = root / "timestamp-evidence.json"
            server._write_new(evidence_path, b"{}\n")
            envelope_path, envelope_raw = server._review_envelope(
                run_dir=root, payload_path=payload_path, payload_raw=payload_raw,
                payload=payload, owner_signature_path=owner_signature_path,
                owner_signature=owner_signature, evidence_path=evidence_path,
                approved=approved)
            reviewer_signature = b"public-reviewer-signature-fixture"
            reviewer_signature_path = root / "e4-reviewer-review-envelope.json.sig"
            server._write_new(reviewer_signature_path, reviewer_signature)
            promotion_path, promotion_raw = server._promotion(
                run_dir=root, payload_path=payload_path, payload_raw=payload_raw,
                owner_signature_path=owner_signature_path,
                owner_signature=owner_signature, envelope_path=envelope_path,
                envelope_raw=envelope_raw,
                reviewer_signature_path=reviewer_signature_path,
                reviewer_signature=reviewer_signature,
                evidence_path=evidence_path, payload=payload, approved=approved)
            self.assertNotIn(b"payload.v12", envelope_raw + promotion_raw)
            self.assertNotIn(b"envelope.v6", envelope_raw + promotion_raw)
            self.assertEqual(
                json.loads(promotion_path.read_bytes())["boundEvidence"]
                ["reviewerEnvelopeSha256"], server._sha_bytes(envelope_raw))

    def test_owner_helper_has_no_reviewer_private_key_capability(self):
        self.assertNotIn("REVIEWER", self.termux.PRIVATE_KEYS)
        self.assertEqual(self.termux.AUTHORIZATION_MS, 15 * 60 * 1000)

    def test_external_reviewer_response_is_exactly_bound(self):
        envelope = (HANDOFF / "e4-reviewer-review-envelope.v5.json").read_bytes()
        signature = (
            HANDOFF / "e4-reviewer-review-envelope.v5.json.sig").read_bytes()
        response = json.dumps({
            "schemaVersion": "e4-independent-reviewer-response.v1",
            "role": "REVIEWER",
            "artifactSha256": server._sha_bytes(envelope),
            "signatureB64": base64.b64encode(signature).decode(),
        }, sort_keys=True).encode()
        accepted = self.termux._review_response_signature(
            response_raw=response,
            artifact_sha256=server._sha_bytes(envelope), raw=envelope)
        self.assertEqual(accepted, signature)
        drift = json.loads(response)
        drift["artifactSha256"] = "0" * 64
        with self.assertRaises(self.termux.HandoffError):
            self.termux._review_response_signature(
                response_raw=json.dumps(drift).encode(),
                artifact_sha256=server._sha_bytes(envelope), raw=envelope)

    @staticmethod
    def eligible_verification():
        return {
            "schemaVersion": "e4-owner-reviewer-verification-result.v1",
            "status": "VERIFIED", "replayEligible": True,
            "ownerSignatureVerified": True,
            "reviewerSignatureVerified": True,
            "exactBindingVerified": True, "freshnessVerified": True,
            "registryStatus": "AUTHENTICATED_ACTIVE",
            "trustedClockAttested": True,
            "executionAuthorized": False, "actionAllowed": False,
            "verificationId": "e4ovr_" + "a" * 64,
            "evaluatedAtEpochMs": NOW + 1,
        }

    def test_atomic_ledger_rolls_back_claim_without_receipt(self):
        with tempfile.TemporaryDirectory(prefix="e4-atomic-test-") as directory:
            path = Path(directory) / "gate.sqlite3"
            ledger = AtomicE4OneShotLedger(str(path))
            ledger.claim(
                verification_result=self.eligible_verification(),
                payload_id="payload-one", envelope_id="envelope-one",
                artifact_digest="b" * 64, claimed_at_epoch_ms=NOW + 1)
            ledger.close()
            with sqlite3.connect(path) as connection:
                table = connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND "
                    "name='e4_owner_reviewer_replay_claims'").fetchone()[0]
            self.assertEqual(table, 0)

    def test_atomic_ledger_commits_claim_and_receipt_together(self):
        with tempfile.TemporaryDirectory(prefix="e4-atomic-test-") as directory:
            path = Path(directory) / "gate.sqlite3"
            plan, approval, receipt, boundary, _auth, _consume = fixture()
            ledger = AtomicE4OneShotLedger(str(path))
            claim = ledger.claim(
                verification_result=self.eligible_verification(),
                payload_id="payload-one", envelope_id="envelope-one",
                artifact_digest="b" * 64, claimed_at_epoch_ms=NOW + 1)
            result = ledger.consume(
                plan=plan, receipt=receipt, owner_approval=approval,
                boundary=boundary, snapshot_ref=SNAPSHOT_REF,
                key_ref=KEY_REF, replay_claim_id=claim["claimId"],
                invocation_identity_sha256="c" * 64,
                invoked_at_epoch_ms=NOW + 1)
            ledger.close()
            with sqlite3.connect(path) as connection:
                replay_count = connection.execute(
                    "SELECT COUNT(*) FROM e4_owner_reviewer_replay_claims"
                ).fetchone()[0]
                receipt_count = connection.execute(
                    "SELECT COUNT(*) FROM e4_rehearsal_receipt_consumptions"
                ).fetchone()[0]
            self.assertEqual(result["status"], "CONSUMED")
            self.assertEqual((replay_count, receipt_count), (1, 1))


if __name__ == "__main__":
    unittest.main()
