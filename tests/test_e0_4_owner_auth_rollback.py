import hashlib
import json
import subprocess
import sys
import tarfile
import shutil
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RELEASE = ROOT / "scripts/e0_4_prepare_owner_auth_release.py"
ROLLBACK = ROOT / "scripts/e0_4_prepare_owner_auth_rollback.py"


def run(*args, check=True):
    return subprocess.run([sys.executable, *map(str, args)], check=check,
                          capture_output=True, text=True)


def build_pair(tmp_path):
    release = tmp_path / "release.tar"
    released = json.loads(run(RELEASE, "--output", release).stdout)
    rollback = tmp_path / "rollback.tar"
    rolled = json.loads(run(ROLLBACK, "--output", rollback, "--release", release,
                            "--release-sha256", released["bundleSha256"],
                            "--release-id", released["releaseId"]).stdout)
    return release, released, rollback, rolled


def test_rollback_preimages_are_exact_bound_and_recover_every_partial_point(tmp_path):
    release, released, rollback, rolled = build_pair(tmp_path)
    with tarfile.open(rollback, "r") as archive:
        manifest = json.load(archive.extractfile("rollback-manifest.json"))
        assert manifest["sourceReleaseId"] == released["releaseId"]
        assert manifest["sourceReleaseSha256"] == released["bundleSha256"]
        assert len(manifest["preimages"]) == 7
        assert sum(item["priorState"] == "PRESENT" for item in manifest["preimages"]) == 6
        absent = [item for item in manifest["preimages"] if item["priorState"] == "ABSENT"]
        assert [item["path"] for item in absent] == ["relay/core/order_access.py"]
        for item in manifest["preimages"]:
            if item["priorState"] == "PRESENT":
                raw = archive.extractfile(item["archivePath"]).read()
                assert hashlib.sha256(raw).hexdigest() == item["sha256"]
    rehearsal = json.loads(run(
        ROLLBACK, "--rehearse", rollback, "--release", release,
        "--release-sha256", released["bundleSha256"], "--release-id", released["releaseId"],
        "--expected-sha256", rolled["bundleSha256"],
        "--expected-rollback-id", rolled["rollbackId"]).stdout)
    assert rehearsal["productionMutation"] is False
    assert rehearsal["allRecovered"] is True
    assert rehearsal["forwardReplacementPoints"] == 8
    assert rehearsal["rollbackInterruptionPointsPerForwardPoint"] == 8
    assert rehearsal["faultMatrixCases"] == 64
    assert {(point["replacedCount"], point["rollbackStepsBeforeInterruption"])
            for point in rehearsal["points"]} == {(a, b) for a in range(8) for b in range(8)}


def test_rollback_is_reproducible_exclusive_and_externally_pinned(tmp_path):
    release = tmp_path / "release.tar"
    released = json.loads(run(RELEASE, "--output", release).stdout)
    bundles, results = [], []
    for name in ("one.tar", "two.tar"):
        path = tmp_path / name
        bundles.append(path)
        results.append(json.loads(run(ROLLBACK, "--output", path, "--release", release,
                                      "--release-sha256", released["bundleSha256"],
                                      "--release-id", released["releaseId"]).stdout))
    assert bundles[0].read_bytes() == bundles[1].read_bytes()
    assert results[0] == results[1]
    existing = tmp_path / "existing.tar"
    existing.write_bytes(b"keep")
    failed = run(ROLLBACK, "--output", existing, "--release", release,
                 "--release-sha256", released["bundleSha256"],
                 "--release-id", released["releaseId"], check=False)
    assert failed.returncode != 0 and existing.read_bytes() == b"keep"
    bad_pin = run(ROLLBACK, "--verify", bundles[0], "--release", release,
                  "--release-sha256", released["bundleSha256"],
                  "--release-id", released["releaseId"], "--expected-sha256", "0" * 64,
                  "--expected-rollback-id", results[0]["rollbackId"], check=False)
    assert bad_pin.returncode != 0 and "external pin" in bad_pin.stderr


def test_dangling_symlink_is_not_treated_as_absent_preimage(tmp_path):
    deployed = tmp_path / "deployed"
    for relative in (
        "relay-fastapi/main.py", "bot/main_bot.py",
        "relay/repositories/order_read_store.py",
        "relay/repositories/payment_session_store.py",
        "relay/repositories/receipt_store.py",
        "relay/repositories/engagement_store.py",
    ):
        target = deployed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path("/opt/obsidian-exchange") / relative, target)
    absent = deployed / "relay/core/order_access.py"
    absent.parent.mkdir(parents=True, exist_ok=True)
    absent.symlink_to("missing-target")
    release = tmp_path / "release.tar"
    released = json.loads(run(RELEASE, "--output", release).stdout)
    result = run(ROLLBACK, "--output", tmp_path / "rollback.tar",
                 "--deployed-root", deployed, "--release", release,
                 "--release-sha256", released["bundleSha256"],
                 "--release-id", released["releaseId"], check=False)
    assert result.returncode != 0
    assert "rollbackId" not in result.stdout
