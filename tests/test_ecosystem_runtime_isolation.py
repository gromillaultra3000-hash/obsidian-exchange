from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_kairos_runtime_is_outside_code_tree():
    source = (ROOT / "kairos/app/kairos_engine.py").read_text(encoding="utf-8")
    main = (ROOT / "kairos/app/main_v19.py").read_text(encoding="utf-8")
    assert 'os.getenv("KAIROS_DATA_DIR")' in source
    assert 'os.getenv("KAIROS_RUNTIME_ENV_FILE")' in source
    assert 'os.getenv("KAIROS_DATA_DIR")' in main
    assert 'os.getenv("KAIROS_RUNTIME_ENV_FILE")' in main


def test_units_use_distinct_non_root_users_and_hardening():
    kairos = (ROOT / "kairos/deploy/zz-runtime.conf").read_text(encoding="utf-8")
    lumi = (ROOT / "lumi/deploy/zz-runtime.conf").read_text(encoding="utf-8")
    assert "User=kairos-svc" in kairos and "User=root" not in kairos
    assert "User=lumi-svc" in lumi and "User=root" not in lumi
    for unit, data_dir in ((kairos, "/var/lib/kairos"), (lumi, "/var/lib/lumi")):
        assert "NoNewPrivileges=true" in unit
        assert "ProtectSystem=strict" in unit
        assert "ProtectHome=true" in unit
        assert "PrivateDevices=true" in unit
        assert "CapabilityBoundingSet=" in unit
        assert f"ReadWritePaths={data_dir}" in unit
    assert "IPAddressDeny=any" in lumi
    assert "IPAddressAllow=localhost" in lumi
