#!/usr/bin/env python3
"""Static safety contract for the production PostgreSQL deployment assets."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/postgres/compose.production.yml"
UNIT = ROOT / "deploy/systemd/obsidian-postgres.service"
EXPECTED_IMAGE = (
    "postgres@sha256:"
    "742f40ea20b9ff2ff31db5458d127452988a2164df9e17441e191f3b72252193"
)


compose = COMPOSE.read_text("utf-8")
unit = UNIT.read_text("utf-8")

image = re.search(r"^\s*image:\s*(\S+)\s*$", compose, re.MULTILINE)
assert image, "PostgreSQL image is missing"
assert re.fullmatch(r"postgres@sha256:[0-9a-f]{64}", image.group(1)), image.group(1)
assert image.group(1) == EXPECTED_IMAGE, "pinned image changed without contract update"
assert "postgres:" not in image.group(1), "mutable PostgreSQL tag is forbidden"
assert 'pull_policy: never' in compose

assert '"127.0.0.1:5432:5432"' in compose
assert "0.0.0.0:5432" not in compose
assert "POSTGRES_PASSWORD:" not in compose
assert "POSTGRES_PASSWORD_FILE: /run/secrets/postgres_password" in compose
assert "file: ${OBSIDIAN_POSTGRES_PASSWORD_FILE:-/etc/obsidian-exchange/postgres/postgres-password}" in compose
assert "name: obsidian-postgres-data" in compose
assert "pg_isready --quiet --username=postgres --dbname=obsidian_exchange" in compose

assert "Requires=docker.service" in unit
assert "ConditionPathExists=/etc/obsidian-exchange/postgres/postgres-password" in unit
assert "compose.production.yml config --quiet" in unit
assert "--abort-on-container-exit --exit-code-from postgres" in unit
assert "State.Health.Status" in unit
assert " compose " in unit and " stop --timeout 120 postgres" in unit
assert " down" not in unit, "unit must never remove the persistent Compose stack"

print("postgres deployment assets: OK")
