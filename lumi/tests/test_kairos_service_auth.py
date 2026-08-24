from fastapi.testclient import TestClient

from lumi.app.core.runtime import runtime_instance
from lumi.app.main import app


TOKEN = "s" * 32
client = TestClient(app)


def test_production_lock_closes_compatibility_mode(monkeypatch):
    runtime_instance.reset_for_tests()
    monkeypatch.setenv("LUMI_PROTECTED_RUNTIME_REQUIRED", "1")
    monkeypatch.setenv("LUMI_KAIROS_TOKEN", TOKEN)

    assert client.get("/health").status_code == 200
    assert client.get("/providers").status_code == 401
    assert client.post("/conflict/resolve", json={}).status_code == 401


def test_kairos_token_is_scoped_to_exact_advisory_posts(monkeypatch):
    runtime_instance.reset_for_tests()
    monkeypatch.setenv("LUMI_PROTECTED_RUNTIME_REQUIRED", "1")
    monkeypatch.setenv("LUMI_KAIROS_TOKEN", TOKEN)
    headers = {"Authorization": f"Bearer {TOKEN}"}

    # The conflict schema has safe defaults, so an empty advisory is accepted;
    # this proves the narrowly scoped service credential passed middleware.
    assert client.post("/conflict/resolve", json={}, headers=headers).status_code == 200
    assert client.post("/integration/hosts/register", json={}, headers=headers).status_code == 422
    assert client.get("/providers", headers=headers).status_code == 401
    assert client.post("/real-apply/execute", json={}, headers=headers).status_code == 401
    assert client.get("/conflict/resolve", headers=headers).status_code == 401


def test_short_service_token_never_opens_advisory_route(monkeypatch):
    runtime_instance.reset_for_tests()
    monkeypatch.setenv("LUMI_PROTECTED_RUNTIME_REQUIRED", "1")
    monkeypatch.setenv("LUMI_KAIROS_TOKEN", "short")
    assert client.post(
        "/conflict/resolve", json={}, headers={"Authorization": "Bearer short"}
    ).status_code == 401
