#!/usr/bin/env python3
"""Compare digest-only v2 catalog manifests without exposing catalog contents."""
import json
import re
import sys
from pathlib import Path

VERSION = "b64-catalog-security-fingerprint.v2"
SECTIONS = {
    "column_acl", "default_acl", "membership", "db_role_setting",
    "relation_security", "constraint_security", "index_security",
    "trigger_security", "function_security", "policy_security",
    "sequence_definition", "type_security", "extension_security",
}
CLUSTER_GLOBAL = {"membership", "db_role_setting"}


def load(path: str) -> dict[str, tuple[int, str]]:
    raw = Path(path).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        value = []
        for line in raw.splitlines():
            parts = line.split("|")
            if len(parts) != 4:
                raise ValueError("invalid_manifest_text_row")
            try:
                parts[2] = int(parts[2])
            except ValueError as exc:
                raise ValueError("invalid_manifest_text_count") from exc
            value.append(parts)
    if not isinstance(value, list) or len(value) != len(SECTIONS):
        raise ValueError("invalid_manifest_shape")
    result = {}
    for row in value:
        if (not isinstance(row, list) or len(row) != 4 or row[0] != VERSION
                or row[1] not in SECTIONS or row[1] in result
                or not isinstance(row[2], int) or row[2] < 0
                or not isinstance(row[3], str)
                or re.fullmatch(r"[0-9a-f]{64}", row[3]) is None):
            raise ValueError("invalid_manifest_entry")
        result[row[1]] = (row[2], row[3])
    if set(result) != SECTIONS:
        raise ValueError("invalid_manifest_sections")
    return result


def main() -> int:
    try:
        source, restored = load(sys.argv[1]), load(sys.argv[2])
        different = sorted(k for k in SECTIONS if source[k] != restored[k])
        global_diff = [k for k in different if k in CLUSTER_GLOBAL]
        local_diff = [k for k in different if k not in CLUSTER_GLOBAL]
        result = {
            "schemaVersion": "b64-catalog-fingerprint-comparison.v1",
            "databaseLocalStatus": "MATCH" if not local_diff else "MISMATCH",
            "differentDatabaseLocalSections": local_diff,
            "clusterGlobalStatus": "MATCH" if not global_diff else "MISMATCH",
            "differentClusterGlobalSections": global_diff,
            "sequenceStateCompared": False,
        }
        print(json.dumps(result, sort_keys=True, separators=(",", ":")))
        return 0 if not different else 1
    except Exception as exc:
        print(json.dumps({"status": "ERROR", "errorType": type(exc).__name__},
                         separators=(",", ":")))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
