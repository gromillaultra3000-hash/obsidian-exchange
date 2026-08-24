import shutil
import sys
import json
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "deploy/postgres"))

from migration_profile import (
    MANIFEST_RELATIVE_PATH,
    MigrationProfileError,
    load_profile,
    selected_paths,
)


def copy_profile(tmp_path: Path) -> Path:
    for source in (ROOT / "deploy/postgres").glob("[0-9][0-9][0-9]_*.sql"):
        target = tmp_path / source.relative_to(ROOT)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    manifest = tmp_path / MANIFEST_RELATIVE_PATH
    manifest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / MANIFEST_RELATIVE_PATH, manifest)
    return tmp_path


def test_exact_profiles_are_disjoint_content_bound_and_non_authorizing():
    value = load_profile(ROOT)
    production = selected_paths(ROOT, "production-cutover")
    dormant = selected_paths(ROOT, "post-cutover-dormant")
    complete = selected_paths(ROOT, "repository-complete")
    assert len(production) == 23
    assert production[-1].name == "023_bot_notification_jobs.sql"
    assert [path.name for path in dormant] == ["024_e3_paper_evidence.sql"]
    assert complete == production + dormant
    assert not set(production) & set(dormant)
    assert value["productionCutover"]["sourceTableCount"] == 54
    assert value["postCutoverDormant"]["addsTables"] == [
        "e3_paper_evidence", "e3_paper_evidence_heads"
    ]
    assert set(value["authority"].values()) == {False}


def test_digest_drift_and_unlisted_numbered_migration_fail_closed(tmp_path):
    copied = copy_profile(tmp_path)
    migration = copied / "deploy/postgres/024_e3_paper_evidence.sql"
    migration.write_text(migration.read_text(encoding="utf-8") + "\n-- drift\n")
    with pytest.raises(MigrationProfileError, match="migration_digest_drift"):
        load_profile(copied)

    copied = copy_profile(tmp_path / "unlisted")
    (copied / "deploy/postgres/025_unlisted.sql").write_text(
        "SELECT 25;\n", encoding="utf-8"
    )
    with pytest.raises(MigrationProfileError, match="inventory_drift"):
        load_profile(copied)


@pytest.mark.parametrize("mutation,reason", [
    (lambda value: value["productionCutover"].__setitem__(
        "maximumVersion", 24), "invalid_production_profile_values"),
    (lambda value: value["productionCutover"].__setitem__(
        "sourceTableCount", 55), "invalid_production_profile_values"),
    (lambda value: value["postCutoverDormant"].__setitem__(
        "addsTables", ["bogus"]), "invalid_dormant_table_inventory"),
    (lambda value: value["postCutoverDormant"].__setitem__(
        "addsFunctions", []), "invalid_dormant_function_inventory"),
    (lambda value: value["postCutoverDormant"]["migrations"][0].__setitem__(
        "path", "deploy/postgres/024_other.sql"),
     "invalid_dormant_migration_inventory"),
])
def test_semantic_profile_metadata_is_closed(tmp_path, mutation, reason):
    copied = copy_profile(tmp_path)
    manifest = copied / MANIFEST_RELATIVE_PATH
    value = json.loads(manifest.read_text(encoding="utf-8"))
    mutation(value)
    manifest.write_text(json.dumps(value), encoding="utf-8")
    with pytest.raises(MigrationProfileError, match=reason):
        load_profile(copied)


def test_runbook_has_no_numbered_migration_wildcard():
    runbook = (ROOT / "docs/postgresql-cutover-runbook.md").read_text("utf-8")
    assert "deploy/postgres/[0-9][0-9][0-9]_*.sql" not in runbook
    assert "--profile production-cutover --paths" in runbook
