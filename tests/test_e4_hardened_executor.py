import copy
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))

from core.e4_hardened_executor import (  # noqa: E402
    HardenedE4Executor, HardenedExecutorError, ImmutableEncryptedSnapshot,
    SnapshotHandle, PlaintextSnapshotHandle, EphemeralFDKeySource,
    SubprocessDockerRuntime,
    validate_authenticated_execution_gate,
)
from core.e4_authenticated_gate_provider import (  # noqa: E402
    VerifierReplayGateProvider,
)
from core.e4_rehearsal_receipt_consumption import (  # noqa: E402
    SQLiteE4RehearsalReceiptLedger,
)
from core.e4_rehearsal_runner_authorization import (  # noqa: E402
    MAX_AUTHORIZATION_MS, PRECONDITIONS, authorize_rehearsal_runner,
    build_owner_approval, build_precondition_evidence,
)
from core.e4_rehearsal_runner_boundary import (  # noqa: E402
    build_runner_boundary, target_spec_fingerprint,
)
from core.e4_rehearsal_runner_plan import (  # noqa: E402
    STEPS, build_rehearsal_runner_plan,
)

NOW = 1_800_000_000_000
TARGET = "e4-hardened-pg-1"
SNAPSHOT = "2" * 64
SNAPSHOT_REF = "snapshot_ref_1"
KEY_REF = "key_handle_1"
MANIFEST = ROOT / "deploy/postgres/proposals/e4_full_snapshot_rehearsal_manifest.json"


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def fixture():
    plan = build_rehearsal_runner_plan(
        evidence_manifest_sha256=hashlib.sha256(MANIFEST.read_bytes()).hexdigest())
    target_digest = target_spec_fingerprint(target_ref=TARGET)
    approval = build_owner_approval(
        approval_ref="owner_approval_e4_hardened_1", plan_id=plan["planId"],
        target_ref=TARGET, target_fingerprint_sha256=target_digest,
        snapshot_sha256=SNAPSHOT,
        snapshot_ref_sha256=digest(SNAPSHOT_REF), key_ref_sha256=digest(KEY_REF),
        approved_at_epoch_ms=NOW, expires_at_epoch_ms=NOW + MAX_AUTHORIZATION_MS)
    evidence = [build_precondition_evidence(
        plan_id=plan["planId"], target_ref=TARGET,
        target_fingerprint_sha256=target_digest, snapshot_sha256=SNAPSHOT,
        check_id=check, observed_at_epoch_ms=NOW, outcome="PASS",
        evidence_sha256=digest(check)) for check in PRECONDITIONS]
    receipt = authorize_rehearsal_runner(
        plan=plan, target_ref=TARGET, target_fingerprint_sha256=target_digest,
        snapshot_sha256=SNAPSHOT, evidence=evidence,
        owner_approval=approval, assessed_at_epoch_ms=NOW + 1)
    boundary = build_runner_boundary(
        plan=plan, receipt=receipt, snapshot_ref=SNAPSHOT_REF, key_ref=KEY_REF)
    authenticated = {
        "planId": plan["planId"], "targetRef": TARGET,
        "snapshotSha256": SNAPSHOT,
        "status": "VERIFIED",
        "promotion": {"registryStatus": "AUTHENTICATED_ACTIVE"},
        "replay": {"status": "CONSUMED", "replayClaimAllowed": True,
                    "claimId": "e4orr_" + "a" * 64},
        "authority": {
            "trustRegistryAuthenticated": True, "trustedClockAttested": True,
            "replayRegistryChecked": True, "replayClaimConsumed": True,
            "executionAuthorized": False,
            "productionDatabaseContactAllowed": False,
            "productionNetworkAllowed": False,
            "productionCredentialsAllowed": False,
            "proposalApplicationAllowed": False,
            "persistentTargetAllowed": False, "promotionAllowed": False,
            "actionAllowed": False, "moneyActionAllowed": False,
            "executionEffect": "NONE",
        },
    }
    consumption = {
        "status": "CONSUMED", "consumptionId": "e4rrc_" + "b" * 64,
        "replayClaimId": "e4orr_" + "a" * 64,
        "planId": plan["planId"], "targetRef": TARGET,
        "snapshotSha256": SNAPSHOT, "boundaryId": boundary["boundaryId"],
        "rehearsalInvocationAllowed": True, "moneyActionAllowed": False,
        "actionAllowed": False, "executionEffect": "NONE",
    }
    return plan, approval, receipt, boundary, authenticated, consumption


class FakeSnapshotSource:
    @contextmanager
    def open_verified(self, *, expected_sha256):
        assert expected_sha256 == SNAPSHOT
        yield SnapshotHandle(
            fd=3, proc_path="/proc/self/fd/3", sha256=SNAPSHOT,
            device=1, inode=2, size_bytes=3)


class FakeKeySource:
    @contextmanager
    def open_key_fd(self):
        yield 4


class FakePlaintextSource:
    @contextmanager
    def open_verified(self, *, expected_sha256):
        yield PlaintextSnapshotHandle(
            fd=5, sha256=expected_sha256, size_bytes=459703)


class FakeRuntime:
    def __init__(self, *, fail_restore=False):
        self.events = []
        self.fail_restore = fail_restore

    def target_absent(self, *, target_ref):
        self.events.append(("absent-before", target_ref))
        return True

    def create_target(self, *, target_ref, plan_id, boundary_id,
                      target_fingerprint):
        self.events.append("create")
        return {"containerId": "a" * 12, "targetRef": target_ref}

    def inspect_owned_target(self, **kwargs):
        self.events.append("inspect")
        return {"containerId": "a" * 12, "targetRef": kwargs["target_ref"],
                "ownershipToken": "token", "containerIdentityCaptured": True}

    def wait_ready(self, **kwargs):
        self.events.append("ready")

    def restore_snapshot(self, **kwargs):
        self.events.append("restore")
        if self.fail_restore:
            raise HardenedExecutorError("synthetic restore failure")

    def restore_plaintext_snapshot(self, **kwargs):
        self.events.append("restore-plaintext")
        if self.fail_restore:
            raise HardenedExecutorError("synthetic restore failure")

    def revoke_post_load_writes(self, **kwargs):
        self.events.append("revoke")

    def collect_read_only_evidence(self, **kwargs):
        self.events.append("evidence")
        return {"tablesSha256": "3" * 64, "aclsSha256": "4" * 64,
                "proposal_absentSha256": "5" * 64, "secretFree": True,
                "productionContacted": False, "writesPerformed": False}

    def destroy_owned_target(self, **kwargs):
        self.events.append("destroy")

    def target_absent_by_identity(self, **kwargs):
        self.events.append("absent-after")
        return True


def gate_provider(authenticated, consumption, events=None):
    events = events if events is not None else []
    def verify(**kwargs):
        events.append("verify")
        return authenticated
    def consume(*, authenticated_evidence, **kwargs):
        events.append("consume")
        return consumption
    return VerifierReplayGateProvider(
        promotion_verifier=verify, replay_consumer=consume), events


class E4HardenedExecutorTests(unittest.TestCase):
    def test_exact_full_container_id_filter_has_no_regex_anchors(self):
        runtime = SubprocessDockerRuntime(
            docker_bin="/bin/true", age_bin="/bin/true")
        calls = []

        def fake_run(argv, **kwargs):
            calls.append(argv)
            return subprocess.CompletedProcess(argv, 0, "", "")

        runtime._run = fake_run
        container_id = "a" * 64
        self.assertTrue(runtime.target_absent_by_identity(
            identity={"containerId": container_id}))
        self.assertEqual(calls, [[
            "/bin/true", "ps", "-aq", "--no-trunc", "--filter",
            f"id={container_id}"]])

    def execute(self, runtime=None, **changes):
        values = fixture()
        authenticated = changes.pop("authenticated_evidence", values[4])
        consumption = changes.pop("replay_consumption", values[5])
        provider, _events = gate_provider(authenticated, consumption)
        args = {
            "plan": values[0], "owner_approval": values[1],
            "receipt": values[2], "boundary": values[3],
            "gate_provider": provider,
            "snapshot_ref": SNAPSHOT_REF, "key_ref": KEY_REF,
            "snapshot_source": FakeSnapshotSource(),
            "key_source": FakeKeySource(),
        }
        args.update(changes)
        runtime = runtime or FakeRuntime()
        return HardenedE4Executor(runtime=runtime, clock=lambda: NOW + 2).execute(**args)

    def test_synthetic_flow_is_exactly_once_and_non_production(self):
        runtime = FakeRuntime()
        result = self.execute(runtime=runtime)
        self.assertEqual(
            result["status"], "NON_PRODUCTION_REHEARSAL_SOURCE_RETENTION_REVIEW")
        self.assertEqual([item["stepId"] for item in result["steps"]],
                         [step for step, _effect in STEPS])
        self.assertFalse(result["authority"]["executionAuthorized"])
        self.assertFalse(result["authority"]["moneyActionAllowed"])
        self.assertTrue(result["snapshot"]["sourceCiphertextRetained"])
        self.assertFalse(result["teardown"]["snapshotDestroyed"])
        self.assertFalse(result["steps"][10]["completed"])
        self.assertFalse(result["steps"][11]["completed"])
        self.assertEqual(runtime.events[-2:], ["destroy", "absent-after"])

    def test_predecrypted_memfd_path_never_requires_server_key(self):
        runtime = FakeRuntime()
        result = self.execute(
            runtime=runtime, key_source=None,
            plaintext_source=FakePlaintextSource(),
            expected_plaintext_sha256="9" * 64)
        self.assertIn("restore-plaintext", runtime.events)
        self.assertNotIn("restore", runtime.events)
        self.assertEqual(result["snapshot"]["decryptionLocation"], "CLIENT_TERMUX")
        self.assertFalse(result["snapshot"]["decryptionKeyReceivedByServer"])
        self.assertTrue(result["snapshot"]["plaintextStreamDigestVerified"])

    def test_authenticated_gate_tamper_fails_before_docker_effect(self):
        runtime = FakeRuntime()
        values = fixture()
        changed = copy.deepcopy(values[4])
        changed["authority"]["actionAllowed"] = True
        with self.assertRaises(HardenedExecutorError):
            self.execute(runtime=runtime, authenticated_evidence=changed)
        self.assertEqual(runtime.events, [])

    def test_replay_claim_and_receipt_binding_tamper_fails_before_docker_effect(self):
        runtime = FakeRuntime()
        values = fixture()
        changed = copy.deepcopy(values[5])
        changed["replayClaimId"] = "e4orr_" + "c" * 64
        with self.assertRaises(HardenedExecutorError):
            self.execute(runtime=runtime, replay_consumption=changed)
        changed = copy.deepcopy(values[5])
        changed["snapshotSha256"] = "f" * 64
        with self.assertRaises(HardenedExecutorError):
            self.execute(runtime=runtime, replay_consumption=changed)
        self.assertEqual(runtime.events, [])

    def test_gate_provider_calls_verifier_before_one_shot_consumer(self):
        values = fixture()
        provider, events = gate_provider(values[4], values[5])
        result = provider.acquire(
            plan=values[0], receipt=values[2], owner_approval=values[1],
            boundary=values[3], snapshot_ref=SNAPSHOT_REF, key_ref=KEY_REF,
            evaluated_at_epoch_ms=NOW + 1)
        self.assertEqual(events, ["verify", "consume"])
        self.assertEqual(result["planId"], values[0]["planId"])

    def test_formal_consumption_returns_replay_and_receipt_bindings(self):
        plan, approval, receipt, boundary, authenticated, _consumption = fixture()
        with tempfile.TemporaryDirectory() as directory:
            result = SQLiteE4RehearsalReceiptLedger(
                str(Path(directory) / "ledger.db")).consume(
                    plan=plan, receipt=receipt, owner_approval=approval,
                    boundary=boundary, snapshot_ref=SNAPSHOT_REF, key_ref=KEY_REF,
                    replay_claim_id=authenticated["replay"]["claimId"],
                    invocation_identity_sha256=digest("invocation-ledger"),
                    invoked_at_epoch_ms=NOW + 2)
        self.assertEqual(result["status"], "CONSUMED")
        self.assertEqual(result["replayClaimId"], authenticated["replay"]["claimId"])
        self.assertEqual(result["planId"], plan["planId"])
        self.assertEqual(result["targetRef"], TARGET)
        self.assertEqual(result["snapshotSha256"], SNAPSHOT)
        self.assertEqual(result["boundaryId"], boundary["boundaryId"])

    def test_restore_failure_destroys_only_owned_target_once(self):
        runtime = FakeRuntime(fail_restore=True)
        with self.assertRaises(HardenedExecutorError):
            self.execute(runtime=runtime)
        self.assertEqual(runtime.events[-2:], ["destroy", "absent-after"])
        self.assertEqual(runtime.events.count("destroy"), 1)

    def test_key_source_rejects_bytes_or_paths(self):
        with self.assertRaises(HardenedExecutorError):
            EphemeralFDKeySource("/tmp/key")
        with self.assertRaises(HardenedExecutorError):
            EphemeralFDKeySource(b"private-key")
        with tempfile.NamedTemporaryFile() as linked:
            fd = os.open(linked.name, os.O_RDONLY)
            try:
                with self.assertRaises(HardenedExecutorError):
                    with EphemeralFDKeySource(fd).open_key_fd():
                        pass
            finally:
                os.close(fd)
        read_fd, write_fd = os.pipe()
        try:
            with EphemeralFDKeySource(read_fd).open_key_fd() as yielded:
                self.assertEqual(yielded, read_fd)
        finally:
            os.close(read_fd)
            os.close(write_fd)

    def test_snapshot_is_inode_and_digest_bound_without_plaintext_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ciphertext.age"
            data = b"synthetic ciphertext only"
            path.write_bytes(data)
            stat = path.stat()
            parent_stat = path.parent.stat()
            source = ImmutableEncryptedSnapshot(
                path=path, expected_sha256=hashlib.sha256(data).hexdigest(),
                expected_device=stat.st_dev, expected_inode=stat.st_ino,
                expected_size_bytes=len(data), expected_hardlink_count=1,
                expected_parent_device=parent_stat.st_dev,
                expected_parent_inode=parent_stat.st_ino,
                require_immutable=False)
            with source.open_verified(expected_sha256=source.expected_sha256) as handle:
                self.assertEqual(handle.sha256, source.expected_sha256)
                self.assertTrue(handle.proc_path.endswith(str(handle.fd)))
            self.assertTrue(path.exists())

    def test_gate_validator_accepts_only_authenticated_consumed_shape(self):
        values = fixture()
        self.assertEqual(
            validate_authenticated_execution_gate(
                authenticated_evidence=values[4], replay_consumption=values[5]
            )["registryStatus"], "AUTHENTICATED_ACTIVE")

    def test_docker_adapter_is_argv_only_and_networkless(self):
        source = (ROOT / "relay/core/e4_hardened_executor.py").read_text()
        for required in (
                "--pull=never", "--network", "\"none\"", "--read-only",
                "--cap-drop", "\"ALL\"", "pass_fds", "shell=False",
                "/proc/self/fd/"):
            self.assertIn(required, source)
        for forbidden in (
                "shell=True", "os.environ", "DATABASE_URL", "obsidian-postgres",
                "--network=host", "\"-p\"", "\"--publish\"",
        ):
            self.assertNotIn(forbidden, source)


if __name__ == "__main__":
    unittest.main()
