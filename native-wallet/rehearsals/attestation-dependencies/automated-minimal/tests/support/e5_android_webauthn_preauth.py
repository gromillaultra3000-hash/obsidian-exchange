"""Test-only Android/WebAuthn pre-authentication boundary.

This module deliberately stops before WebAuthn cryptographic verification.  It
only creates and validates two role-specific, short-lived challenge sessions
for the future reviewer/owner flow.  It has no network, Android SDK, storage,
credential enrollment, signature verification, wallet signing, or issuer
selection side effect.
"""

from __future__ import annotations

import base64
import hashlib
import json
import re
from collections.abc import Mapping, MutableSet
from urllib.parse import urlsplit


SCHEMA = "native-wallet-e5-android-webauthn-preauth-session.v1"
PAIR_SCHEMA = "native-wallet-e5-android-webauthn-role-links.v1"
PROFILE = "WEBAUTHN_L3_CTAP22_ROAMING_ES256_UV"
CLIENT_DATA_TYPE = "webauthn.get"
MAX_LIFETIME_MS = 600_000
MAX_FUTURE_SKEW_MS = 1_000
CHALLENGE_BYTES = 32
ALLOWED_ROLES = frozenset({"reviewer", "owner"})
HEX64 = re.compile(r"^[0-9a-f]{64}$")
TOKEN = re.compile(r"^[a-z0-9][a-z0-9._:-]{0,127}$")
RP_ID = re.compile(r"^[a-z0-9](?:[a-z0-9.-]{0,61}[a-z0-9])?$")


class PreAuthSessionError(ValueError):
    """Raised when a test-only pre-auth session is unsafe or inconsistent."""


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _token(value: object, field: str) -> str:
    if not isinstance(value, str) or TOKEN.fullmatch(value) is None:
        raise PreAuthSessionError(f"{field} is invalid")
    if value in {"server", "operator", "builder", "generator", "verifier"}:
        raise PreAuthSessionError(f"{field} must identify a human-controlled domain")
    return value


def _digest(value: object, field: str) -> str:
    if not isinstance(value, str) or HEX64.fullmatch(value) is None:
        raise PreAuthSessionError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _context(value: Mapping[str, object]) -> dict[str, str]:
    required = {
        "decision_result_sha256",
        "handoff_sha256",
        "scorecard_sha256",
    }
    if not isinstance(value, Mapping) or set(value) != required:
        raise PreAuthSessionError("exact review context digests are required")
    return {
        key: _digest(value[key], key)
        for key in sorted(required)
    }


def _time(value: object, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise PreAuthSessionError(f"{field} must be a positive integer")
    return value


def _origin(rp_id: object, origin: object) -> tuple[str, str]:
    if not isinstance(rp_id, str) or RP_ID.fullmatch(rp_id) is None:
        raise PreAuthSessionError("rp_id is invalid")
    if not isinstance(origin, str):
        raise PreAuthSessionError("origin is invalid")
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or parsed.hostname != rp_id
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
    ):
        raise PreAuthSessionError("origin must be the exact HTTPS origin for rp_id")
    return rp_id, f"https://{rp_id}"


def _challenge(
    *, session_id: str, role: str, context: Mapping[str, str],
    rp_id: str, origin: str,
) -> bytes:
    material = {
        "domain": "obsidian.e5.android-webauthn-preauth.v1",
        "session_id": session_id,
        "role": role,
        "context": dict(context),
        "rp_id": rp_id,
        "origin": origin,
    }
    return hashlib.sha256(_canonical(material)).digest()


def _link(*, origin: str, role: str, session_id: str) -> str:
    # review.invalid is intentional in the tests: this is an inert example
    # link, not a deployed endpoint or an invitation to enter credentials.
    return f"{origin}/e5/webauthn/{role}/{session_id}"


def _expected_session(
    *,
    role: str,
    human_identity_id: str,
    trust_domain_id: str,
    context: Mapping[str, str],
    rp_id: str,
    origin: str,
    issued_at_epoch_ms: int,
    expires_at_epoch_ms: int,
    caller_nonce_sha256: str,
) -> dict[str, object]:
    seed = {
        "schema": SCHEMA,
        "role": role,
        "human_identity_id": human_identity_id,
        "trust_domain_id": trust_domain_id,
        "context": dict(context),
        "rp_id": rp_id,
        "origin": origin,
        "issued_at_epoch_ms": issued_at_epoch_ms,
        "expires_at_epoch_ms": expires_at_epoch_ms,
        "caller_nonce_sha256": caller_nonce_sha256,
    }
    session_id = "e5s_" + _sha256(_canonical(seed))[:32]
    challenge = _challenge(
        session_id=session_id, role=role, context=context,
        rp_id=rp_id, origin=origin,
    )
    challenge_b64url = base64.urlsafe_b64encode(challenge).decode("ascii").rstrip("=")
    return {
        "schema": SCHEMA,
        "sessionId": session_id,
        "role": role,
        "humanIdentityId": human_identity_id,
        "trustDomainId": trust_domain_id,
        "context": dict(context),
        "rpId": rp_id,
        "origin": origin,
        "issuedAtEpochMs": issued_at_epoch_ms,
        "expiresAtEpochMs": expires_at_epoch_ms,
        "callerNonceSha256": caller_nonce_sha256,
        "challengeB64Url": challenge_b64url,
        "challengeSha256": _sha256(challenge),
        "link": _link(origin=origin, role=role, session_id=session_id),
        "webauthn": {
            "profile": PROFILE,
            "clientDataType": CLIENT_DATA_TYPE,
            "backupEligible": False,
            "backupState": False,
            "userPresentRequired": True,
            "userVerifiedRequired": True,
            "requiredAuthenticatorFlagsByte": 0x05,
            "exactRpIdRequired": True,
            "exactOriginRequired": True,
        },
        "preAuth": {
            "cryptographicVerificationImplemented": False,
            "authenticated": False,
            "selectionAllowed": False,
            "cryptoCallAllowed": False,
            "runtimeIntegrationAllowed": False,
        },
    }


def create_preauth_session(
    *,
    role: str,
    human_identity_id: str,
    trust_domain_id: str,
    context: Mapping[str, object],
    rp_id: str,
    origin: str,
    issued_at_epoch_ms: int,
    expires_at_epoch_ms: int,
    caller_nonce_sha256: str,
) -> dict[str, object]:
    """Create an inert, role-specific challenge session."""
    if role not in ALLOWED_ROLES:
        raise PreAuthSessionError("role must be reviewer or owner")
    identity = _token(human_identity_id, "human_identity_id")
    trust_domain = _token(trust_domain_id, "trust_domain_id")
    if identity == trust_domain:
        raise PreAuthSessionError("identity and trust domain must be distinct")
    normalized_context = _context(context)
    normalized_rp_id, normalized_origin = _origin(rp_id, origin)
    issued = _time(issued_at_epoch_ms, "issued_at_epoch_ms")
    expires = _time(expires_at_epoch_ms, "expires_at_epoch_ms")
    if expires <= issued or expires - issued > MAX_LIFETIME_MS:
        raise PreAuthSessionError("session lifetime is invalid")
    nonce = _digest(caller_nonce_sha256, "caller_nonce_sha256")
    return _expected_session(
        role=role,
        human_identity_id=identity,
        trust_domain_id=trust_domain,
        context=normalized_context,
        rp_id=normalized_rp_id,
        origin=normalized_origin,
        issued_at_epoch_ms=issued,
        expires_at_epoch_ms=expires,
        caller_nonce_sha256=nonce,
    )


def _required_fields() -> set[str]:
    return {
        "schema", "sessionId", "role", "humanIdentityId", "trustDomainId",
        "context", "rpId", "origin", "issuedAtEpochMs", "expiresAtEpochMs",
        "callerNonceSha256", "challengeB64Url", "challengeSha256", "link",
        "webauthn", "preAuth",
    }


def validate_preauth_session(
    value: Mapping[str, object],
    *,
    expected_context: Mapping[str, object],
    now_epoch_ms: int,
    expected_role: str | None = None,
    consumed_session_ids: MutableSet[str] | None = None,
    consumed_nonces: MutableSet[str] | None = None,
) -> dict[str, object]:
    """Validate shape/binding/expiry/replay while granting no authority."""
    if not isinstance(value, Mapping) or set(value) != _required_fields():
        raise PreAuthSessionError("pre-auth session shape is not closed")
    if value.get("schema") != SCHEMA:
        raise PreAuthSessionError("pre-auth session schema is invalid")
    role = value.get("role")
    if role not in ALLOWED_ROLES or (expected_role is not None and role != expected_role):
        raise PreAuthSessionError("session role is not the expected role")
    now = _time(now_epoch_ms, "now_epoch_ms")
    issued = _time(value.get("issuedAtEpochMs"), "issuedAtEpochMs")
    expires = _time(value.get("expiresAtEpochMs"), "expiresAtEpochMs")
    if not (
        issued <= now + MAX_FUTURE_SKEW_MS
        and expires > now
        and expires > issued
        and expires - issued <= MAX_LIFETIME_MS
    ):
        raise PreAuthSessionError("session is expired or outside the time window")
    if consumed_session_ids is not None and value.get("sessionId") in consumed_session_ids:
        raise PreAuthSessionError("session id was already consumed")
    if consumed_nonces is not None and value.get("callerNonceSha256") in consumed_nonces:
        raise PreAuthSessionError("caller nonce was already consumed")
    expected = create_preauth_session(
        role=role,
        human_identity_id=value.get("humanIdentityId"),
        trust_domain_id=value.get("trustDomainId"),
        context=value.get("context"),
        rp_id=value.get("rpId"),
        origin=value.get("origin"),
        issued_at_epoch_ms=issued,
        expires_at_epoch_ms=expires,
        caller_nonce_sha256=value.get("callerNonceSha256"),
    )
    if dict(value) != expected:
        raise PreAuthSessionError("session digest, challenge, link, or policy drifted")
    expected_normalized_context = _context(expected_context)
    if value["context"] != expected_normalized_context:
        raise PreAuthSessionError("session is bound to a different review context")
    return {
        "schema": "native-wallet-e5-android-webauthn-preauth-validation.v1",
        "sessionId": value["sessionId"],
        "role": value["role"],
        "preAuthStructurallyValid": True,
        "cryptographicVerificationImplemented": False,
        "authenticated": False,
        "selectionAllowed": False,
        "cryptoCallAllowed": False,
        "runtimeIntegrationAllowed": False,
    }


def validate_role_pair(
    reviewer: Mapping[str, object],
    owner: Mapping[str, object],
    *,
    expected_context: Mapping[str, object],
    now_epoch_ms: int,
    consumed_session_ids: MutableSet[str] | None = None,
    consumed_nonces: MutableSet[str] | None = None,
) -> dict[str, object]:
    """Validate two independent role links for the same exact context."""
    reviewer_result = validate_preauth_session(
        reviewer,
        expected_context=expected_context,
        expected_role="reviewer",
        now_epoch_ms=now_epoch_ms,
        consumed_session_ids=consumed_session_ids,
        consumed_nonces=consumed_nonces,
    )
    owner_result = validate_preauth_session(
        owner,
        expected_context=expected_context,
        expected_role="owner",
        now_epoch_ms=now_epoch_ms,
        consumed_session_ids=consumed_session_ids,
        consumed_nonces=consumed_nonces,
    )
    if reviewer["sessionId"] == owner["sessionId"]:
        raise PreAuthSessionError("reviewer and owner sessions must be distinct")
    if reviewer["humanIdentityId"] == owner["humanIdentityId"]:
        raise PreAuthSessionError("reviewer and owner identities must be independent")
    if reviewer["trustDomainId"] == owner["trustDomainId"]:
        raise PreAuthSessionError("reviewer and owner trust domains must be independent")
    if reviewer["callerNonceSha256"] == owner["callerNonceSha256"]:
        raise PreAuthSessionError("reviewer and owner nonces must be independent")
    if (reviewer["rpId"], reviewer["origin"]) != (owner["rpId"], owner["origin"]):
        raise PreAuthSessionError("reviewer and owner must use the exact same RP/origin")
    return {
        "schema": PAIR_SCHEMA,
        "reviewerSessionId": reviewer_result["sessionId"],
        "ownerSessionId": owner_result["sessionId"],
        "sameContext": True,
        "independentIdentities": True,
        "independentTrustDomains": True,
        "preAuthPairStructurallyValid": True,
        "cryptographicVerificationImplemented": False,
        "authenticated": False,
        "selectionAllowed": False,
        "cryptoCallAllowed": False,
        "runtimeIntegrationAllowed": False,
    }


def create_role_links(
    *,
    context: Mapping[str, object],
    rp_id: str,
    origin: str,
    issued_at_epoch_ms: int,
    expires_at_epoch_ms: int,
    reviewer_identity_id: str,
    reviewer_trust_domain_id: str,
    reviewer_caller_nonce_sha256: str,
    owner_identity_id: str,
    owner_trust_domain_id: str,
    owner_caller_nonce_sha256: str,
) -> dict[str, object]:
    """Issue both inert role links and check their pairwise separation."""
    reviewer = create_preauth_session(
        role="reviewer",
        human_identity_id=reviewer_identity_id,
        trust_domain_id=reviewer_trust_domain_id,
        context=context,
        rp_id=rp_id,
        origin=origin,
        issued_at_epoch_ms=issued_at_epoch_ms,
        expires_at_epoch_ms=expires_at_epoch_ms,
        caller_nonce_sha256=reviewer_caller_nonce_sha256,
    )
    owner = create_preauth_session(
        role="owner",
        human_identity_id=owner_identity_id,
        trust_domain_id=owner_trust_domain_id,
        context=context,
        rp_id=rp_id,
        origin=origin,
        issued_at_epoch_ms=issued_at_epoch_ms,
        expires_at_epoch_ms=expires_at_epoch_ms,
        caller_nonce_sha256=owner_caller_nonce_sha256,
    )
    pair = validate_role_pair(
        reviewer,
        owner,
        expected_context=context,
        now_epoch_ms=issued_at_epoch_ms,
    )
    return {
        "schema": PAIR_SCHEMA,
        "reviewer": reviewer,
        "owner": owner,
        "pairValidation": pair,
        "authenticated": False,
        "selectionAllowed": False,
        "cryptoCallAllowed": False,
        "runtimeIntegrationAllowed": False,
    }


def consume_for_test_only(
    value: Mapping[str, object],
    *,
    expected_context: Mapping[str, object],
    now_epoch_ms: int,
    consumed_session_ids: MutableSet[str],
    consumed_nonces: MutableSet[str],
    expected_role: str | None = None,
) -> dict[str, object]:
    """Record one structural use, modelling the future single-use gate."""
    result = validate_preauth_session(
        value,
        expected_context=expected_context,
        now_epoch_ms=now_epoch_ms,
        expected_role=expected_role,
        consumed_session_ids=consumed_session_ids,
        consumed_nonces=consumed_nonces,
    )
    consumed_session_ids.add(value["sessionId"])
    consumed_nonces.add(value["callerNonceSha256"])
    return result
