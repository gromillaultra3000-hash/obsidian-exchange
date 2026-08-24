#!/usr/bin/env python3
"""Create a deterministic, non-authorizing E0.4 candidate release bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
BASES = {
    "relay-fastapi/main.py":"c1ef783e3005f4698540ddc5368ef9a4592612fcf666b403ecbb7c4a359bd7ff",
    "bot/main_bot.py":"a015b5b12870fa2f1eec7d0fb638cc2c94cb90235850d474ebb25455446372fb",
    "relay/repositories/order_read_store.py":"2cc91c733a8388ac2f643016fe192f7687ef0c44b79305d23fed50dcfd2ca06d",
    "relay/repositories/payment_session_store.py":"eb41d099a06beac4251190d10221467bdca4b21db7bc97dba687dd8d40653b8e",
    "relay/repositories/receipt_store.py":"252ada0ad673dfb60ad3f18913b11aa0a6bfa90d647978af71a97651cc54e123",
    "relay/repositories/engagement_store.py":"9c989eaba773416b1414a0e652130ffea529cff4fcd6158c4e58285da59464b0",
    "relay/core/order_access.py":None,
}
SQL_EVIDENCE = {
    "deploy/postgres/proposals/028_e0_relay_acl_envelope.sql":"91601ad8a803772261e612a8101ddd8c9099d6c2b7f94f09888967202b30fa28",
    "deploy/postgres/proposals/032_e0_relay_p3_authorized_order_reads.sql":"d155a41f78ac03bb337dbd5b16ca7f3122d9ca5278f1a0de1d7af4a0c1069e62",
    "deploy/postgres/proposals/035_e0_bot_b1_role_envelope.sql":"9c3b1cb2e0601dc5a5e328213f69642ca4d147b9e64681c24146c1da70c3ceec",
    "deploy/postgres/proposals/042_e0_bot_b3_1_engagement_non_money_writers.sql":"18ca6c872292c76ba3db739c5c42a565856f2ef1246fd7b2ed5908a94248a172",
}


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode() + b"\n"


def add_bytes(archive, name, raw):
    info = tarfile.TarInfo(name)
    info.size, info.mode, info.mtime = len(raw), 0o644, 0
    info.uid = info.gid = 0
    info.uname = info.gname = ""
    archive.addfile(info, io.BytesIO(raw))


def _normalized_member(info):
    return (info.isfile() and info.mode == 0o644 and info.mtime == 0 and
            info.uid == 0 and info.gid == 0 and info.uname == "" and
            info.gname == "" and not info.pax_headers)


def verify_bundle(bundle, expected_sha256, expected_release_id):
    raw_bundle = bundle.read_bytes()
    if sha(raw_bundle) != expected_sha256:
        raise ValueError("bundle digest does not match external pin")
    with tarfile.open(bundle, "r") as archive:
        members = archive.getmembers()
        names = [item.name for item in members]
        if len(names) != len(set(names)) or names != sorted(names):
            raise ValueError("bundle members are duplicate or unsorted")
        if any(name.startswith("/") or "\\" in name or ".." in Path(name).parts
               for name in names):
            raise ValueError("unsafe bundle member path")
        if not all(_normalized_member(item) for item in members):
            raise ValueError("non-normalized bundle member")
        manifest = json.load(archive.extractfile("release-manifest.json"))
        digest_body = dict(manifest)
        digest_body.pop("manifestDigest", None)
        digest_body.pop("releaseId", None)
        expected_digest = sha(canonical(digest_body))
        if manifest.get("manifestDigest") != expected_digest:
            raise ValueError("manifest digest mismatch")
        if manifest.get("releaseId") != "e04rel_" + expected_digest[:32]:
            raise ValueError("release id mismatch")
        if manifest.get("releaseId") != expected_release_id:
            raise ValueError("release id does not match external pin")
        expected = {item["archivePath"]:(item["sha256"], item["bytes"])
                    for item in manifest["candidateArtifacts"] + manifest["sqlEvidence"]}
        expected["release-manifest.json"] = (sha(canonical(manifest)), len(canonical(manifest)))
        if names != sorted(expected):
            raise ValueError("bundle allowlist mismatch")
        for member in members:
            raw = archive.extractfile(member).read()
            digest, size = expected[member.name]
            if len(raw) != size or sha(raw) != digest:
                raise ValueError(f"bundle payload mismatch: {member.name}")
    return manifest


def prepare(output, deployed_root, source_root):
    with tempfile.TemporaryDirectory(prefix="e04-release-") as td:
        candidate = Path(td) / "candidate"
        build = subprocess.run([
            sys.executable, str(source_root / "scripts/e0_4_build_owner_auth_candidate.py"),
            "--relay-base", str(deployed_root / "relay-fastapi/main.py"),
            "--relay-source", str(source_root / "relay-fastapi/main.py"),
            "--bot-base", str(deployed_root / "bot/main_bot.py"),
            "--bot-source", str(source_root / "bot/main_bot.py"),
            "--deployed-root", str(deployed_root),
            "--source-root", str(source_root),
            "--output-dir", str(candidate),
        ], check=True, capture_output=True, text=True)
        build_evidence = {item["component"]:item for item in json.loads(build.stdout)["artifacts"]}
        path_components = {
            "relay-fastapi/main.py":"relay", "bot/main_bot.py":"bot",
            "relay/core/order_access.py":"order_access",
            "relay/repositories/order_read_store.py":"order_read_store",
            "relay/repositories/payment_session_store.py":"payment_session_store",
            "relay/repositories/receipt_store.py":"receipt_store",
            "relay/repositories/engagement_store.py":"engagement_store",
        }
        artifacts = []
        payloads = {}
        for path in sorted(candidate.rglob("*.py")):
            relative = path.relative_to(candidate).as_posix()
            raw = path.read_bytes()
            payloads[f"candidate/{relative}"] = raw
            component = path_components[relative]
            built = build_evidence[component]
            target = deployed_root / relative
            metadata_source = target if target.exists() else target.parent
            stat = metadata_source.stat()
            if stat.st_uid != 0 or stat.st_gid != 0:
                raise ValueError(f"unexpected production ownership: {relative}")
            artifacts.append({"component":component, "path":relative,
                              "archivePath":f"candidate/{relative}",
                              "targetPath":f"/opt/obsidian-exchange/{relative}",
                              "artifactType":"PYTHON_SOURCE", "mode":"0644",
                              "targetUid":0,"targetGid":0,
                              "sha256":sha(raw), "bytes":len(raw),
                              "deployedBaseSha256":BASES[relative],
                              "sourceSha256":built["sourceSha256"],
                              "selectedFunctions":built["selectedFunctions"]})
        sql = []
        for relative, expected in sorted(SQL_EVIDENCE.items()):
            raw = (source_root / relative).read_bytes()
            if sha(raw) != expected:
                raise ValueError(f"SQL evidence digest mismatch: {relative}")
            payloads[f"rehearsal-evidence/{relative}"] = raw
            sql.append({"path":relative,"archivePath":f"rehearsal-evidence/{relative}",
                        "sha256":expected,"bytes":len(raw),"deployable":False})
        body = {
            "schemaVersion":"e0-4-owner-auth-release-manifest.v1",
            "route":"E0/E0.4/FEATURE_STATUS_SURFACE_MATRIX",
            "productionAuthorization":False,
            "deploymentAuthorized":False,
            "restartAuthorized":False,
            "databaseMigrationAuthorized":False,
            "deployable":False,
            "productionDeployed":False,
            "preflightOnlyAuthorized":True,
            "authorization":{name:False for name in (
                "productionMutation","databaseMigration","deploy","configWrite",
                "serviceStop","serviceRestart","credentialChange","telegramDelivery",
                "trafficCutover","moneyWriter","liveTrade")},
            "ownerApprovalRequired":True,
            "digestAlgorithm":"SHA-256",
            "digestScope":"canonical compact ASCII JSON with LF, excluding manifestDigest and releaseId",
            "provenance":{
                "candidateBuilder":{"path":"scripts/e0_4_build_owner_auth_candidate.py",
                                    "sha256":sha((source_root / "scripts/e0_4_build_owner_auth_candidate.py").read_bytes())},
                "releaseBuilder":{"path":"scripts/e0_4_prepare_owner_auth_release.py",
                                  "sha256":sha(Path(__file__).read_bytes())},
                "dirtyWorktree":True
            },
            "candidateArtifacts":artifacts,
            "sqlEvidence":sql,
            "featureFlags":[
                {"name":"RELAY_P3_AUTHORIZED_READ_FUNCTIONS_ENABLED","default":"OFF"},
                {"name":"BOT_B3_ENGAGEMENT_ACL_ADAPTER_ENABLED","default":"OFF"},
            ],
            "excludedPatterns":["*.env","*.db","*.log","__pycache__","venv",".feature_index","credentials","secrets"],
            "blockers":[
                "The included SQL files are proposal/rehearsal evidence and are not production migration artifacts.",
                "Proposals 028 and 035 contain disposable role-envelope assumptions and synthetic credential operations.",
                "A production-specific expand/validate/rollback migration and owner-authorized maintenance decision are absent."
                ,"Exact production catalog preimage and SQL rollback/forward-repair artifacts are not hash-bound or rehearsed."
            ],
            "rolloutOrder":[
                "verify exact deployed base hashes and preserve rollback bytes",
                "apply separately reviewed narrow additive production-specific expand SQL while flags remain OFF and without revoking legacy direct SQL",
                "validate exact functions, owners, search_path, PUBLIC denial and EXECUTE; confirm production legacy privileges are unchanged and relation denial only under isolated execute-only principals",
                "stage and hash all seven payloads, coordinate service stop, then use per-file atomic replacement with partial-point recovery while flags remain OFF",
                "restart and health-check Relay, then bot, without exercising money writers",
                "enable the Relay function-adapter flag, restart Relay, run bounded owner/foreign/token canary and observe",
                "enable the bot function-adapter flag, restart the single bot poller, run a transaction-rolled-back function-level synthetic review probe and observe",
            ],
            "rollbackOrder":[
                "disable the affected function-adapter flag and restart that service",
                "if code rollback is required, stop both services and use the separately hash-bound rollback archive to restore six exact prior files plus the verified prior absence of order_access, including owner/group/mode",
                "restart Relay then the single bot poller and verify prior hashes/health",
                "retain additive SQL functions during incident rollback; revoke/drop only in a later reviewed contract step"
            ]
        }
        body["manifestDigest"] = sha(canonical(body))
        body["releaseId"] = "e04rel_" + body["manifestDigest"][:32]
        payloads["release-manifest.json"] = canonical(body)
        fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
        with os.fdopen(fd, "wb") as handle, tarfile.open(fileobj=handle, mode="w", format=tarfile.USTAR_FORMAT) as archive:
            for name in sorted(payloads):
                add_bytes(archive, name, payloads[name])
        raw = output.read_bytes()
        bundle_digest = sha(raw)
        verify_bundle(output, bundle_digest, body["releaseId"])
        return {"releaseId":body["releaseId"], "bundleSha256":bundle_digest,
                "bundleBytes":len(raw), "deployable":False,
                "productionAuthorization":False}


def main():
    parser = argparse.ArgumentParser()
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--output", type=Path)
    action.add_argument("--verify", type=Path)
    parser.add_argument("--deployed-root", type=Path,
                        default=Path("/opt/obsidian-exchange"))
    parser.add_argument("--source-root", type=Path, default=ROOT)
    parser.add_argument("--expected-sha256")
    parser.add_argument("--expected-release-id")
    args = parser.parse_args()
    if args.verify:
        if not args.expected_sha256 or not args.expected_release_id:
            parser.error("--verify requires --expected-sha256 and --expected-release-id external pins")
        manifest = verify_bundle(args.verify, args.expected_sha256, args.expected_release_id)
        print(json.dumps({"releaseId":manifest["releaseId"],"verified":True}, sort_keys=True))
    else:
        print(json.dumps(prepare(args.output, args.deployed_root, args.source_root), sort_keys=True))


if __name__ == "__main__":
    main()
