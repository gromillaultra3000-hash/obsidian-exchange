import base64
import hashlib
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SUPPORT = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/support"
sys.path.insert(0, str(SUPPORT))

from e5_android_webauthn_preauth import create_role_links  # noqa: E402
from e5_android_webauthn_rp_contract import handle_test_only_request  # noqa: E402


NOW = 1_800_000_000_000
CONTEXT = {
    "decision_result_sha256": "a" * 64,
    "handoff_sha256": "b" * 64,
    "scorecard_sha256": "c" * 64,
}
RP_ID = "review.invalid"
ORIGIN = "https://review.invalid"


def _b64(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _links():
    return create_role_links(
        context=CONTEXT,
        rp_id=RP_ID,
        origin=ORIGIN,
        issued_at_epoch_ms=NOW,
        expires_at_epoch_ms=NOW + 60_000,
        reviewer_identity_id="human-reviewer-a",
        reviewer_trust_domain_id="domain-review-a",
        reviewer_caller_nonce_sha256=hashlib.sha256(b"reviewer").hexdigest(),
        owner_identity_id="human-owner-b",
        owner_trust_domain_id="domain-owner-b",
        owner_caller_nonce_sha256=hashlib.sha256(b"owner").hexdigest(),
    )


def _assertion(session):
    client_data = json.dumps(
        {
            "type": "webauthn.get",
            "challenge": session["challengeB64Url"],
            "origin": ORIGIN,
        },
        separators=(",", ":"),
    ).encode()
    auth_data = hashlib.sha256(RP_ID.encode()).digest() + b"\x05\x00\x00\x00\x01"
    return {
        "schema": "native-wallet-ed25519-corpus-review-assertion-envelope.v1",
        "evidence_id": "assertion-proof-01",
        "credential_id_base64url": _b64(b"credential-id"),
        "client_data_json_base64url": _b64(client_data),
        "authenticator_data_base64url": _b64(auth_data),
        "signature_base64url": _b64(b"synthetic-signature"),
        "user_handle_base64url": None,
    }


def test_get_returns_role_specific_public_session_view():
    links = _links()
    sessions = {
        links["reviewer"]["sessionId"]: links["reviewer"],
        links["owner"]["sessionId"]: links["owner"],
    }
    reviewer_status, reviewer = handle_test_only_request(
        method="GET",
        path=f"/e5/webauthn/reviewer/{links['reviewer']['sessionId']}",
        body=None,
        sessions=sessions,
        expected_context=CONTEXT,
        now_epoch_ms=NOW + 1,
    )
    owner_status, owner = handle_test_only_request(
        method="GET",
        path=f"/e5/webauthn/owner/{links['owner']['sessionId']}",
        body=None,
        sessions=sessions,
        expected_context=CONTEXT,
        now_epoch_ms=NOW + 1,
    )
    assert reviewer_status == owner_status == 200
    assert reviewer["role"] == "reviewer"
    assert owner["role"] == "owner"
    assert reviewer["sessionId"] != owner["sessionId"]
    assert reviewer["challengeB64Url"] != owner["challengeB64Url"]
    assert reviewer["authenticated"] is False


def test_post_runs_preflight_but_never_authenticates_or_consumes():
    links = _links()
    session = links["reviewer"]
    sessions = {session["sessionId"]: session}
    status, response = handle_test_only_request(
        method="POST",
        path=f"/e5/webauthn/reviewer/{session['sessionId']}/assertion",
        body=json.dumps({"assertion": _assertion(session)}, separators=(",", ":")).encode(),
        sessions=sessions,
        expected_context=CONTEXT,
        now_epoch_ms=NOW + 1,
    )
    assert status == 200
    assert response["status"] == "PREFLIGHT_ONLY"
    assert response["preflight"]["preflightStructurallyValid"] is True
    assert response["preflight"]["signatureValid"] is False
    assert response["authenticated"] is False
    assert response["selectionAllowed"] is False
    assert response["replayLedgerConfigured"] is False
    assert response["consumptionPerformed"] is False
    assert b"synthetic-signature" not in json.dumps(response).encode()


def test_route_and_context_fail_closed():
    links = _links()
    session = links["owner"]
    sessions = {session["sessionId"]: session}
    cases = [
        ("GET", "/e5/webauthn/reviewer/unknown", None, 404, CONTEXT),
        ("GET", f"/e5/webauthn/reviewer/{session['sessionId']}", None, 409,
         {**CONTEXT, "scorecard_sha256": "d" * 64}),
        ("GET", f"/e5/webauthn/owner/{session['sessionId']}?next=1", None, 404, CONTEXT),
        ("PUT", f"/e5/webauthn/owner/{session['sessionId']}/assertion", b"{}", 405, CONTEXT),
        ("POST", f"/e5/webauthn/owner/{session['sessionId']}/assertion", b"{}", 400, CONTEXT),
    ]
    for method, path, body, expected_status, context in cases:
        status, response = handle_test_only_request(
            method=method,
            path=path,
            body=body,
            sessions=sessions,
            expected_context=context,
            now_epoch_ms=NOW + 1,
        )
        assert status == expected_status
        assert response["authenticated"] is False
        assert response["runtimeIntegrationAllowed"] is False


def test_bad_assertion_returns_no_raw_details():
    links = _links()
    session = links["owner"]
    sessions = {session["sessionId"]: session}
    bad = _assertion(session)
    bad["signature_base64url"] += "="
    status, response = handle_test_only_request(
        method="POST",
        path=f"/e5/webauthn/owner/{session['sessionId']}/assertion",
        body=json.dumps({"assertion": bad}).encode(),
        sessions=sessions,
        expected_context=CONTEXT,
        now_epoch_ms=NOW + 1,
    )
    assert status == 422
    assert response["errorCode"] == "ASSERTION_PREFLIGHT_REJECTED"
    assert "signature" not in json.dumps(response).lower()
