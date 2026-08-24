import hashlib
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/support"
sys.path.insert(0, str(SUPPORT))

from e5_android_webauthn_preauth import create_role_links  # noqa: E402
from e5_android_webauthn_test_server import (  # noqa: E402
    TestOnlyRpApplication,
    TestOnlyRpConfig,
    TestServerConfigError,
)


NOW = 1_800_000_000_000
CONTEXT = {
    "decision_result_sha256": "a" * 64,
    "handoff_sha256": "b" * 64,
    "scorecard_sha256": "c" * 64,
}


def _links():
    return create_role_links(
        context=CONTEXT,
        rp_id="localhost",
        origin="https://localhost",
        issued_at_epoch_ms=NOW,
        expires_at_epoch_ms=NOW + 60_000,
        reviewer_identity_id="human-reviewer-a",
        reviewer_trust_domain_id="domain-review-a",
        reviewer_caller_nonce_sha256=hashlib.sha256(b"reviewer").hexdigest(),
        owner_identity_id="human-owner-b",
        owner_trust_domain_id="domain-owner-b",
        owner_caller_nonce_sha256=hashlib.sha256(b"owner").hexdigest(),
    )


def _config(**changes):
    values = dict(
        bind_host="127.0.0.1",
        bind_port=8443,
        rp_id="localhost",
        origin="https://localhost",
        tls_certificate_file="/tmp/e5-test-cert.pem",
        tls_private_key_file="/tmp/e5-test-key.pem",
    )
    values.update(changes)
    return TestOnlyRpConfig(**values)


def test_config_is_loopback_only_and_requires_exact_https_origin():
    assert _config().validate().bind_host == "127.0.0.1"
    for changes in [
        {"bind_host": "0.0.0.0"},
        {"bind_host": "192.0.2.10"},
        {"bind_port": 443},
        {"origin": "http://localhost"},
        {"origin": "https://other.invalid"},
        {"rp_id": "pay.obsidianbtc.org", "origin": "https://pay.obsidianbtc.org"},
        {"tls_certificate_file": "relative.pem"},
    ]:
        try:
            _config(**changes).validate()
        except TestServerConfigError:
            pass
        else:
            raise AssertionError("unsafe test-server configuration was accepted")


def test_application_is_explicit_and_does_not_mutate_session_map():
    links = _links()
    sessions = {
        links["reviewer"]["sessionId"]: links["reviewer"],
        links["owner"]["sessionId"]: links["owner"],
    }
    before = dict(sessions)
    app = TestOnlyRpApplication(
        sessions=sessions,
        expected_context=CONTEXT,
        now_epoch_ms=lambda: NOW + 1,
    )
    status, response = app.dispatch(
        method="GET",
        path=f"/e5/webauthn/reviewer/{links['reviewer']['sessionId']}",
        body=None,
    )
    assert status == 200
    assert response["action"] == "ASSERTION_PREFLIGHT_ONLY"
    assert response["authenticated"] is False
    assert sessions == before


def test_server_module_has_no_automatic_start_or_production_authority():
    source = (SUPPORT / "e5_android_webauthn_test_server.py").read_text()
    for forbidden in (
        "serve_forever()", "0.0.0.0", "os.environ", "requests", "fastapi",
        "uvicorn", "credential_enrolled",
    ):
        assert forbidden not in source.lower()
