from pathlib import Path


ROOT = Path("/root")
UNIT = (ROOT / "deploy/relay-fastapi-zz-runtime.conf").read_text(encoding="utf-8")
MAIN = (ROOT / "relay-fastapi/main.py").read_text(encoding="utf-8")
IDENTITY = (ROOT / "relay/core/kairos_service_identity.py").read_text(encoding="utf-8")
LOGGER = (ROOT / "relay/utils/logger.py").read_text(encoding="utf-8")
SHADOW = (ROOT / "deploy/relay-shadow.service").read_text(encoding="utf-8")


def test_relay_unit_is_non_root_and_strictly_sandboxed():
    for required in (
        "User=relay-svc", "Group=relay-svc", "ProtectSystem=strict",
        "ProtectHome=true", "NoNewPrivileges=true", "PrivateDevices=true",
        "CapabilityBoundingSet=", "ReadWritePaths=/var/lib/obsidian-exchange-receipts",
        "RestrictAddressFamilies=AF_UNIX AF_INET AF_INET6",
    ):
        assert required in UNIT
    assert "ReadWritePaths=/var/lib/obsidian-exchange " not in UNIT
    assert "ReadWritePaths=/var/lib/obsidian-exchange-wallet" not in UNIT


def test_shadow_can_disable_all_background_workers():
    assert 'os.getenv("RELAY_BACKGROUND_TASKS_ENABLED", "1")' in MAIN
    gate = MAIN.index('os.getenv("RELAY_BACKGROUND_TASKS_ENABLED", "1")')
    first_task = MAIN.index("asyncio.create_task(_session_cleanup_loop())")
    assert gate < first_task
    assert "User=relay-svc" in SHADOW
    assert "Environment=RELAY_BACKGROUND_TASKS_ENABLED=0" in SHADOW
    assert "Environment=RELAY_PORT=15001" in SHADOW


def test_identity_keys_live_in_dedicated_directory():
    assert "/etc/obsidian-relay/signing.key" in IDENTITY
    assert "/etc/obsidian-relay/principal.key" in IDENTITY
    assert "/etc/obsidian-exchange/relay-identity/" not in IDENTITY
    assert "/etc/obsidian-exchange/relay-kairos-signing.key" not in IDENTITY


def test_internal_mutations_use_signed_body_and_exact_scopes():
    assert "def signed_request(" in IDENTITY
    assert 'method not in {"GET", "POST", "DELETE"}' in IDENTITY
    assert 'headers["Content-Type"] = content_type' in IDENTITY
    assert "sort_keys=True" in IDENTITY


def test_provider_logger_ignores_legacy_shared_log_override():
    assert "Environment=RELAY_PROVIDER_LOG_DIR=/var/log/obsidian-relay" in UNIT
    assert "RELAY_PROVIDER_LOG_DIR') or os.getenv(" in LOGGER
