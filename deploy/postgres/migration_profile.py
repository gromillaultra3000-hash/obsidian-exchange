#!/usr/bin/env python3
"""Validate and list the exact production/dormant PostgreSQL migrations."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any


MANIFEST_RELATIVE_PATH = Path("deploy/postgres/migration-profile.v1.json")
MIGRATION_RE = re.compile(r"^deploy/postgres/([0-9]{3})_[a-z0-9_]+\.sql$")


class MigrationProfileError(RuntimeError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _entries(value: Any, label: str) -> list[dict[str, str]]:
    if not isinstance(value, list) or not value:
        raise MigrationProfileError(f"invalid_{label}_entries")
    result = []
    for item in value:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise MigrationProfileError(f"invalid_{label}_entry")
        path = item["path"]
        digest = item["sha256"]
        if (not isinstance(path, str) or not MIGRATION_RE.fullmatch(path)
                or not isinstance(digest, str)
                or not re.fullmatch(r"[0-9a-f]{64}", digest)):
            raise MigrationProfileError(f"invalid_{label}_binding")
        result.append({"path": path, "sha256": digest})
    return result


def load_profile(root: Path) -> dict[str, Any]:
    root = root.resolve()
    manifest_path = root / MANIFEST_RELATIVE_PATH
    try:
        value = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise MigrationProfileError("migration_profile_unreadable") from exc
    if not isinstance(value, dict) or set(value) != {
        "schemaVersion", "productionCutover", "postCutoverDormant", "authority"
    }:
        raise MigrationProfileError("invalid_migration_profile_fields")
    if value["schemaVersion"] != "obsidian-postgres-migration-profile.v1":
        raise MigrationProfileError("invalid_migration_profile_version")
    production = value["productionCutover"]
    dormant = value["postCutoverDormant"]
    authority = value["authority"]
    if not isinstance(production, dict) or set(production) != {
        "profileStatus", "maximumVersion", "sourceTableCount", "migrations"
    }:
        raise MigrationProfileError("invalid_production_profile")
    if (production["profileStatus"] != "FROZEN_001_023_SOURCE_PROFILE"
            or type(production["maximumVersion"]) is not int
            or production["maximumVersion"] != 23
            or type(production["sourceTableCount"]) is not int
            or production["sourceTableCount"] != 54):
        raise MigrationProfileError("invalid_production_profile_values")
    if not isinstance(dormant, dict) or set(dormant) != {
        "disposition", "migrations", "addsTables", "addsFunctions"
    }:
        raise MigrationProfileError("invalid_dormant_profile")
    if dormant["disposition"] != \
            "REPOSITORY_PRESENT_PRODUCTION_STATE_UNKNOWN_NOT_REOBSERVED":
        raise MigrationProfileError("invalid_dormant_disposition")
    if dormant["addsTables"] != [
        "e3_paper_evidence", "e3_paper_evidence_heads"
    ]:
        raise MigrationProfileError("invalid_dormant_table_inventory")
    if dormant["addsFunctions"] != [
        "e3_reject_evidence_mutation()",
        "e3_append_paper_evidence(text,text,text,bigint,text,text,jsonb)",
    ]:
        raise MigrationProfileError("invalid_dormant_function_inventory")
    if authority != {
        "migrationApplyAuthorized": False,
        "productionContactAuthorized": False,
        "aclGrantAuthorized": False,
        "principalProvisioningAuthorized": False,
        "actionAllowed": False,
    }:
        raise MigrationProfileError("invalid_migration_profile_authority")

    production_entries = _entries(production["migrations"], "production")
    dormant_entries = _entries(dormant["migrations"], "dormant")
    if [entry["path"] for entry in dormant_entries] != [
        "deploy/postgres/024_e3_paper_evidence.sql"
    ]:
        raise MigrationProfileError("invalid_dormant_migration_inventory")
    all_entries = production_entries + dormant_entries
    paths = [entry["path"] for entry in all_entries]
    if len(paths) != len(set(paths)):
        raise MigrationProfileError("duplicate_migration_path")
    versions = [int(MIGRATION_RE.fullmatch(path).group(1)) for path in paths]
    maximum = production["maximumVersion"]
    if versions[:len(production_entries)] != list(range(1, maximum + 1)):
        raise MigrationProfileError("production_migrations_not_contiguous")
    if versions[len(production_entries):] != list(
        range(maximum + 1, maximum + 1 + len(dormant_entries))
    ):
        raise MigrationProfileError("dormant_migrations_not_contiguous")

    actual_numbered = sorted(
        path.relative_to(root).as_posix()
        for path in (root / "deploy/postgres").glob("[0-9][0-9][0-9]_*.sql")
    )
    if sorted(paths) != actual_numbered:
        raise MigrationProfileError("numbered_migration_inventory_drift")
    for entry in all_entries:
        if _sha256(root / entry["path"]) != entry["sha256"]:
            raise MigrationProfileError(f"migration_digest_drift:{entry['path']}")
    return value


def selected_paths(root: Path, profile: str) -> list[Path]:
    value = load_profile(root)
    production = value["productionCutover"]["migrations"]
    dormant = value["postCutoverDormant"]["migrations"]
    selected = {
        "production-cutover": production,
        "post-cutover-dormant": dormant,
        "repository-complete": production + dormant,
    }[profile]
    return [root.resolve() / item["path"] for item in selected]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[2])
    parser.add_argument(
        "--profile",
        choices=("production-cutover", "post-cutover-dormant", "repository-complete"),
        default="production-cutover",
    )
    parser.add_argument("--paths", action="store_true")
    args = parser.parse_args()
    try:
        paths = selected_paths(args.root, args.profile)
    except MigrationProfileError as exc:
        print(json.dumps({"status": "NO_GO", "reason": str(exc)}, sort_keys=True))
        return 2
    if args.paths:
        for path in paths:
            print(path.relative_to(args.root.resolve()).as_posix())
    else:
        print(json.dumps({
            "status": "MATCH",
            "profile": args.profile,
            "migrations": [path.name for path in paths],
        }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
