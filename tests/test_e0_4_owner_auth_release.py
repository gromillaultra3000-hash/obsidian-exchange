import hashlib
import json
import io
import shutil
import subprocess
import sys
import tarfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/e0_4_prepare_owner_auth_release.py"


def test_release_bundle_is_reproducible_non_authorizing_and_closed(tmp_path):
    outputs = []
    for name in ("one.tar", "two.tar"):
        path = tmp_path / name
        result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(path)],
                                check=True, capture_output=True, text=True)
        outputs.append((path, json.loads(result.stdout)))
    assert outputs[0][0].read_bytes() == outputs[1][0].read_bytes()
    assert outputs[0][1] == outputs[1][1]
    result = outputs[0][1]
    assert result["deployable"] is False and result["productionAuthorization"] is False
    assert result["bundleSha256"] == hashlib.sha256(outputs[0][0].read_bytes()).hexdigest()
    with tarfile.open(outputs[0][0], "r") as archive:
        names = archive.getnames()
        assert names == sorted(names)
        assert len(names) == 12
        manifest = json.load(archive.extractfile("release-manifest.json"))
        assert manifest["releaseId"] == result["releaseId"]
        assert manifest["deployable"] is False
        assert all(item["deployable"] is False for item in manifest["sqlEvidence"])
        assert {item["default"] for item in manifest["featureFlags"]} == {"OFF"}
        assert len(manifest["candidateArtifacts"]) == 7
        assert manifest["blockers"]
        digest_body = dict(manifest)
        digest_body.pop("manifestDigest")
        digest_body.pop("releaseId")
        expected_digest = hashlib.sha256(
            (json.dumps(digest_body, sort_keys=True, separators=(",", ":"),
                        ensure_ascii=True) + "\n").encode()).hexdigest()
        assert manifest["manifestDigest"] == expected_digest
        assert manifest["releaseId"] == "e04rel_" + expected_digest[:32]
        bound = {item["archivePath"]:item
                 for item in manifest["candidateArtifacts"] + manifest["sqlEvidence"]}
        for member in archive.getmembers():
            assert member.isfile() and member.mode == 0o644 and member.mtime == 0
            assert member.uid == member.gid == 0
            assert member.uname == member.gname == "" and not member.pax_headers
            if member.name in bound:
                raw = archive.extractfile(member).read()
                assert len(raw) == bound[member.name]["bytes"]
                assert hashlib.sha256(raw).hexdigest() == bound[member.name]["sha256"]
        forbidden = (".env", ".db", ".log", "venv", "feature_index")
        assert not any(any(part in name for part in forbidden) for name in names)
    verified = subprocess.run([sys.executable, str(SCRIPT), "--verify", str(outputs[0][0]),
                              "--expected-sha256", result["bundleSha256"],
                              "--expected-release-id", result["releaseId"]],
                              check=True, capture_output=True, text=True)
    assert json.loads(verified.stdout) == {"releaseId":result["releaseId"],"verified":True}


def test_release_output_is_exclusive(tmp_path):
    output = tmp_path / "existing.tar"
    output.write_bytes(b"owner-data")
    result = subprocess.run([sys.executable, str(SCRIPT), "--output", str(output)],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert output.read_bytes() == b"owner-data"


def test_release_is_identical_from_explicit_copied_roots(tmp_path):
    deployed, source = tmp_path / "deployed", tmp_path / "source"
    deployed_files = [
        "relay-fastapi/main.py", "bot/main_bot.py",
        "relay/repositories/order_read_store.py",
        "relay/repositories/payment_session_store.py",
        "relay/repositories/receipt_store.py",
        "relay/repositories/engagement_store.py",
    ]
    source_files = deployed_files + ["relay/core/order_access.py",
        "scripts/e0_4_build_owner_auth_candidate.py",
        "deploy/postgres/proposals/028_e0_relay_acl_envelope.sql",
        "deploy/postgres/proposals/032_e0_relay_p3_authorized_order_reads.sql",
        "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql",
        "deploy/postgres/proposals/042_e0_bot_b3_1_engagement_non_money_writers.sql"]
    for relative in deployed_files:
        target = deployed / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(Path("/opt/obsidian-exchange") / relative, target)
    (deployed / "relay/core").mkdir(parents=True, exist_ok=True)
    for relative in source_files:
        target = source / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    default, copied = tmp_path / "default.tar", tmp_path / "copied.tar"
    subprocess.run([sys.executable, str(SCRIPT), "--output", str(default)], check=True)
    subprocess.run([sys.executable, str(SCRIPT), "--output", str(copied),
                    "--deployed-root", str(deployed), "--source-root", str(source)], check=True)
    assert default.read_bytes() == copied.read_bytes()


def test_release_verifier_rejects_traversal_member(tmp_path):
    bad = tmp_path / "bad.tar"
    with tarfile.open(bad, "w", format=tarfile.USTAR_FORMAT) as archive:
        raw = b"x"
        info = tarfile.TarInfo("../escape")
        info.size, info.mode, info.mtime = len(raw), 0o644, 0
        info.uid = info.gid = 0
        info.uname = info.gname = ""
        archive.addfile(info, io.BytesIO(raw))
    result = subprocess.run([sys.executable, str(SCRIPT), "--verify", str(bad),
                            "--expected-sha256", hashlib.sha256(bad.read_bytes()).hexdigest(),
                            "--expected-release-id", "e04rel_invalid"],
                            capture_output=True, text=True)
    assert result.returncode != 0


def test_release_verifier_rejects_self_consistent_rehashed_tamper(tmp_path):
    original = tmp_path / "original.tar"
    built = json.loads(subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(original)], check=True,
        capture_output=True, text=True).stdout)
    tampered = tmp_path / "tampered.tar"
    with tarfile.open(original, "r") as source:
        payloads = {m.name: source.extractfile(m).read() for m in source.getmembers()}
    manifest = json.loads(payloads["release-manifest.json"])
    manifest["productionDeployed"] = True
    body = dict(manifest)
    body.pop("manifestDigest")
    body.pop("releaseId")
    raw_body = (json.dumps(body, sort_keys=True, separators=(",", ":"),
                           ensure_ascii=True) + "\n").encode()
    manifest["manifestDigest"] = hashlib.sha256(raw_body).hexdigest()
    manifest["releaseId"] = "e04rel_" + manifest["manifestDigest"][:32]
    payloads["release-manifest.json"] = (json.dumps(
        manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=True) + "\n").encode()
    with tarfile.open(tampered, "w", format=tarfile.USTAR_FORMAT) as archive:
        for name in sorted(payloads):
            raw = payloads[name]
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = len(raw), 0o644, 0
            info.uid = info.gid = 0
            info.uname = info.gname = ""
            archive.addfile(info, io.BytesIO(raw))
    result = subprocess.run([sys.executable, str(SCRIPT), "--verify", str(tampered),
                            "--expected-sha256", built["bundleSha256"],
                            "--expected-release-id", built["releaseId"]],
                            capture_output=True, text=True)
    assert result.returncode != 0
    assert "external pin" in result.stderr
