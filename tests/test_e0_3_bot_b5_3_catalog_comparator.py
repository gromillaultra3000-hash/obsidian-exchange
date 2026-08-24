import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "deploy/postgres/b64_compare_catalog_fingerprints.py"
VERSION = "b64-catalog-security-fingerprint.v2"
SECTIONS = (
    "column_acl", "default_acl", "membership", "db_role_setting",
    "relation_security", "constraint_security", "index_security",
    "trigger_security", "function_security", "policy_security",
    "sequence_definition", "type_security", "extension_security",
)


def manifest():
    return [[VERSION, section, 0, "a" * 64] for section in SECTIONS]


def run(tmp_path, left, right):
    paths = []
    for name, value in (("left.json", left), ("right.json", right)):
        path = tmp_path / name
        path.write_text(json.dumps(value), encoding="utf-8")
        paths.append(path)
    return subprocess.run([sys.executable, str(SCRIPT), *map(str, paths)], text=True,
                          capture_output=True, check=False)


def test_exact_match_and_database_local_mismatch_are_separate(tmp_path):
    good = manifest()
    assert run(tmp_path, good, good).returncode == 0
    drift = manifest()
    drift[0][2] = 1
    result = run(tmp_path, good, drift)
    assert result.returncode == 1
    output = json.loads(result.stdout)
    assert output["differentDatabaseLocalSections"] == ["column_acl"]
    assert output["differentClusterGlobalSections"] == []


def test_missing_duplicate_unknown_version_count_and_hash_fail_closed(tmp_path):
    cases = []
    cases.append(manifest()[:-1])
    duplicate = manifest(); duplicate[-1][1] = duplicate[0][1]; cases.append(duplicate)
    version = manifest(); version[0][0] = "wrong"; cases.append(version)
    count = manifest(); count[0][2] = -1; cases.append(count)
    digest = manifest(); digest[0][3] = "not-a-hash"; cases.append(digest)
    for malformed in cases:
        result = run(tmp_path, manifest(), malformed)
        assert result.returncode == 2
        assert json.loads(result.stdout)["status"] == "ERROR"
