import copy
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_owner_payload_refresh import (  # noqa: E402
    MAX_AUTHORIZATION_MS,
    PayloadRefreshError,
    main,
    refresh_owner_payload,
)


SOURCE = ROOT / "E4-owner-handoff" / "e4-owner-decision-payload.v8.json"
NOW = 1_787_500_000_123
NONCE = bytes(range(32))


class OwnerPayloadRefreshTests(unittest.TestCase):
    def setUp(self):
        self.source = json.loads(SOURCE.read_text(encoding="utf-8"))

    def test_refresh_changes_only_fresh_identity_fields(self):
        self.assertEqual(MAX_AUTHORIZATION_MS, 15 * 60 * 1000)
        value = refresh_owner_payload(
            source=self.source, approved_at_epoch_ms=NOW, nonce=NONCE)
        self.assertEqual(
            value["payloadId"],
            "e4-owner-decision-payload-20260823-10-1787500000123")
        self.assertEqual(value["supersedes"], self.source["payloadId"])
        self.assertEqual(
            value["approval"]["approvalRef"],
            "e4-approval-20260823-10-1787500000123")
        self.assertEqual(value["approval"]["approvedAtEpochMs"], NOW)
        self.assertEqual(
            value["approval"]["expiresAtEpochMs"],
            NOW + MAX_AUTHORIZATION_MS)
        self.assertEqual(
            value["replay"]["nonceSha256"],
            "630dcd2966c4336691125448bbb25b4ff412a49c732db2c8abc1b8581bd710dd")
        self.assertEqual(value["frozenBinding"], self.source["frozenBinding"])
        self.assertEqual(
            value["approval"]["snapshotSha256"],
            self.source["approval"]["snapshotSha256"])
        self.assertTrue(all(
            item is False for item in value["authority"].values()
            if isinstance(item, bool)))
        self.assertEqual(value["authority"]["executionEffect"], "NONE")
        self.assertEqual(
            self.source["payloadId"],
            "e4-owner-decision-payload-20260823-09-1787447323203")

    def test_refresh_rejects_non_fail_closed_source(self):
        unsafe = copy.deepcopy(self.source)
        unsafe["authority"]["executionAuthorized"] = True
        with self.assertRaisesRegex(PayloadRefreshError, "not fail-closed"):
            refresh_owner_payload(
                source=unsafe, approved_at_epoch_ms=NOW, nonce=NONCE)

    def test_refresh_rejects_bad_nonce(self):
        with self.assertRaisesRegex(PayloadRefreshError, "exactly 32 bytes"):
            refresh_owner_payload(
                source=self.source, approved_at_epoch_ms=NOW,
                nonce=b"too-short")

    def test_refresh_rejects_unsafe_approval(self):
        unsafe = copy.deepcopy(self.source)
        unsafe["approval"]["productionNetworkAllowed"] = True
        with self.assertRaisesRegex(PayloadRefreshError, "not fail-closed"):
            refresh_owner_payload(
                source=unsafe, approved_at_epoch_ms=NOW, nonce=NONCE)

    def test_refresh_rejects_extra_authority_field(self):
        unsafe = copy.deepcopy(self.source)
        unsafe["authority"]["newExecutionAuthority"] = True
        with self.assertRaisesRegex(PayloadRefreshError, "authority fields"):
            refresh_owner_payload(
                source=unsafe, approved_at_epoch_ms=NOW, nonce=NONCE)

    def test_refresh_rejects_frozen_binding_drift(self):
        unsafe = copy.deepcopy(self.source)
        unsafe["frozenBinding"]["planSourceSha256"] = "0" * 64
        with self.assertRaisesRegex(PayloadRefreshError, "frozen binding differs"):
            refresh_owner_payload(
                source=unsafe, approved_at_epoch_ms=NOW, nonce=NONCE)

    def test_refresh_rejects_unexpected_top_level_secret_field(self):
        unsafe = copy.deepcopy(self.source)
        unsafe["privateKey"] = "must-never-be-copied"
        with self.assertRaisesRegex(PayloadRefreshError, "top-level fields"):
            refresh_owner_payload(
                source=unsafe, approved_at_epoch_ms=NOW, nonce=NONCE)

    def test_refresh_rejects_trust_clock_and_route_drift(self):
        for mutate in (
                lambda value: value["trustAnchors"]["owner"].update(
                    publicKeySha256="0" * 64),
                lambda value: value["trustedClock"].update(
                    provider="UNTRUSTED"),
                lambda value: value["signaturePlan"].update(
                    ownerNamespace="wrong"),
                lambda value: value.update(stage="E5")):
            unsafe = copy.deepcopy(self.source)
            mutate(unsafe)
            with self.assertRaises(PayloadRefreshError):
                refresh_owner_payload(
                    source=unsafe, approved_at_epoch_ms=NOW, nonce=NONCE)

    def test_refresh_rejects_public_instruction_drift(self):
        unsafe = copy.deepcopy(self.source)
        unsafe["nextAction"] = "paste a private key here"
        with self.assertRaisesRegex(
                PayloadRefreshError, "public instructions differ"):
            refresh_owner_payload(
                source=unsafe, approved_at_epoch_ms=NOW, nonce=NONCE)

    def test_cli_writes_once_and_prints_bounded_result(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "e4-owner-decision-payload.v9.json"
            with mock.patch(
                    "core.e4_owner_payload_refresh.os.urandom",
                    return_value=NONCE):
                with mock.patch("builtins.print") as printed:
                    self.assertEqual(main([
                        "--source", str(SOURCE), "--output", str(output),
                        "--now-epoch-ms", str(NOW),
                    ]), 0)
            self.assertEqual(stat_mode(output), 0o644)
            written = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(written["approval"]["approvedAtEpochMs"], NOW)
            lines = [call.args[0] for call in printed.call_args_list]
            self.assertIn("AUTHORITY=NONE", lines)
            with contextlib.redirect_stderr(io.StringIO()):
                with self.assertRaises(SystemExit) as failure:
                    main([
                        "--source", str(SOURCE), "--output", str(output),
                        "--now-epoch-ms", str(NOW),
                    ])
            self.assertEqual(failure.exception.code, 2)


def stat_mode(path: Path) -> int:
    return os.stat(path).st_mode & 0o777


if __name__ == "__main__":
    unittest.main()
