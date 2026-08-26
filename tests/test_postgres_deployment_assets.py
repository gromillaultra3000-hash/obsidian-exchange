#!/usr/bin/env python3
"""Static safety contract for the production PostgreSQL deployment assets."""

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ROOT / "deploy/postgres/compose.production.yml"
UNIT = ROOT / "deploy/systemd/obsidian-postgres.service"
WATCHDOG_UNIT = ROOT / "deploy/systemd/obsidian-b64-snapshot-reader-watchdog.service"
ACTIVATION_UNIT = ROOT / "deploy/systemd/obsidian-b64-064a-activation.service"
EXPECTED_IMAGE = (
    "postgres@sha256:"
    "7456ef82e5f5bc43d997f4781bbd7c0d6389bff397564649a356e206ba473aee"
)
EXPECTED_IMPLEMENTATION_RELEASE = (
    "/opt/obsidian-exchange/releases/e0-e0.3-b5.3-064a/"
    "fbcf49928f82d22d277521ab1e388f3aec63046d/"
    "deploy/postgres/"
)


compose = COMPOSE.read_text("utf-8")
unit = UNIT.read_text("utf-8")
watchdog_unit = WATCHDOG_UNIT.read_text("utf-8")
activation_unit = ACTIVATION_UNIT.read_text("utf-8")

image = re.search(r"^\s*image:\s*(\S+)\s*$", compose, re.MULTILINE)
assert image, "PostgreSQL image is missing"
assert re.fullmatch(r"postgres@sha256:[0-9a-f]{64}", image.group(1)), image.group(1)
assert image.group(1) == EXPECTED_IMAGE, "pinned image changed without contract update"
assert "postgres:" not in image.group(1), "mutable PostgreSQL tag is forbidden"
assert 'pull_policy: never' in compose
assert "platform: linux/amd64" in compose

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
assert "up --force-recreate" in unit
assert "ConditionPathExists=/opt/obsidian-exchange/deploy/postgres/verify_b64_snapshot_reader.py" in unit
assert "State.Health.Status" in unit
assert "b64_snapshot_reader_transition_gate.py" in unit
assert "b64_snapshot_reader_transition_gate.py --expected-image-id" in unit
assert "--expected-server-version-num 170011 --apply" in unit
assert "b64_snapshot_reader_watchdog.py" in unit
assert f"ExecStartPost=/opt/obsidian-exchange/relay-venv/bin/python -B {EXPECTED_IMPLEMENTATION_RELEASE}b64_snapshot_reader_watchdog.py" in unit

supervisor = (
    ROOT / "deploy/systemd/obsidian-b64-dump-restore-supervisor.service"
).read_text()
authenticated_acceptance = (
    ROOT / "deploy/systemd/obsidian-b64-authenticated-evidence-acceptance.service"
).read_text()
supervisor_timer = (
    ROOT / "deploy/systemd/obsidian-b64-dump-restore-supervisor.timer"
).read_text()
assert "30114cbb7ce25d49b3313d04f6564903bc29074a" in supervisor
assert "b64_dump_restore_supervisor.py" in supervisor
assert "--rehearsal-root" in supervisor and "--evidence-root" in supervisor
assert "--require-authenticated-evidence" not in supervisor
assert "ConditionPathExists=/run/systemd/timesync/synchronized" in supervisor
assert "RestrictAddressFamilies=AF_UNIX" in supervisor
assert "OnUnitActiveSec=6h" in supervisor_timer
assert "--require-authenticated-evidence" in authenticated_acceptance
assert "--authentication-root" in authenticated_acceptance
assert "--keyring-relative keyring.json" in authenticated_acceptance
assert "--acceptance-relative acceptance-signed.json" in authenticated_acceptance
assert "a83cfac0c2a61edb83480ae782e077d3fafc6401b3e2f1694aeebf6fd24b113c" in authenticated_acceptance
assert "b482504a2166b1e410e6a4b97829dbfcf818807b872f6ca73530a6d130dd54ba" in authenticated_acceptance
assert authenticated_acceptance.count(
    "ConditionPathExists=/opt/obsidian-exchange/evidence/"
) == 2
assert "OnUnitActiveSec" not in authenticated_acceptance
assert "--expected-server-version-num 170011 --require-dormant" in unit
assert "b64_postgres_shutdown.py" in unit
assert "Wants=obsidian-b64-snapshot-reader-watchdog.timer" in unit
assert "ReadWritePaths=/run/lock /var/lib/docker/volumes/obsidian-postgres-data/_data/.obsidian-b64-hba-v1" in unit
assert "--require-dormant" in watchdog_unit
assert "--cleanup-recovery" in watchdog_unit
assert "--cleanup-recovery" not in unit
assert f"ExecStart=/opt/obsidian-exchange/relay-venv/bin/python -B {EXPECTED_IMPLEMENTATION_RELEASE}b64_snapshot_reader_watchdog.py" in watchdog_unit
assert watchdog_unit.count(f"ConditionPathExists={EXPECTED_IMPLEMENTATION_RELEASE}") == 4
assert "IMPLEMENTATION_COMMIT" not in activation_unit
assert f"WorkingDirectory={EXPECTED_IMPLEMENTATION_RELEASE.removesuffix('deploy/postgres/').removesuffix('/')}" in activation_unit
assert f"ExecStart=/opt/obsidian-exchange/relay-venv/bin/python -B -E {EXPECTED_IMPLEMENTATION_RELEASE}b64_064a_activation_launcher.py" in activation_unit
assert "BindsTo=obsidian-postgres.service" in watchdog_unit
assert "ReadWritePaths=/run/lock /var/lib/docker/volumes/obsidian-postgres-data/_data/.obsidian-b64-hba-v1 -/var/lib/obsidian-exchange/b64-064a-activation/journal -/var/lib/obsidian-exchange/b64-064a-activation/resources -/var/lib/obsidian-exchange/b64-064a-activation/workspace -/var/lib/obsidian-exchange/b64-064a-activation/proxy" in watchdog_unit
assert "TimeoutStartSec=180" in watchdog_unit
assert "SuccessExitStatus=" not in watchdog_unit
assert "KillMode=control-group" in watchdog_unit
assert " down" not in unit, "unit must never remove the persistent Compose stack"

consumer_dropins = sorted((ROOT / "deploy/systemd").glob("*-zz-postgres.conf"))
assert len(consumer_dropins) == 7
for dropin in consumer_dropins:
    value = dropin.read_text("utf-8")
    assert "Requires=obsidian-postgres.service" in value, dropin
    assert "BindsTo=obsidian-postgres.service" in value, dropin
    assert "After=obsidian-postgres.service" in value, dropin

print("postgres deployment assets: OK")
