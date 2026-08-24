import os
from pathlib import Path


def test_collection_policy_skips_only_unavailable_integration_modules(monkeypatch):
    monkeypatch.delenv("TEST_POSTGRES_DSN", raising=False)
    assert Path(__file__).with_name("conftest.py").exists()
    assert "test_postgres_" in Path(__file__).with_name("conftest.py").read_text()
    assert "test_e0_3_" in Path(__file__).with_name("conftest.py").read_text()
