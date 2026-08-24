#!/usr/bin/env python3
"""Offline candidate-key signer for bounded 064A evidence; never grants production authority."""
from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import json
import os
import secrets
import stat
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from core.b64_064a_decision import (  # noqa: E402
    MAX_LIFETIME_SECONDS, build_owner_envelope, build_reviewer_envelope,
    build_statement, verify_decision,
)

MAX_FILE = 1024 * 1024
ROUTE = "E0/E0.3/B5.3/064A"
KEYRING_SCHEMA = "b64-064a-public-key-registry-candidate.v1"
ROLES = {"ACCOUNTABLE_OWNER", "INDEPENDENT_REVIEWER"}
V2_CANDIDATE_KEYS = {
    "schemaVersion", "project", "route", "requestedDecision", "effect",
    "candidateStatus", "sourceObservation", "sourceBinding",
    "immutablePriorState", "knownBlockers", "authority",
}


class SafeError(Exception):
    pass


def _receipt(receipt_status: str, **values: object) -> None:
    print(json.dumps({"receiptStatus": receipt_status, **values}, sort_keys=True, separators=(",", ":")))


def _walk_parent(path: Path) -> None:
    if not path.is_absolute():
        raise SafeError("PATH_NOT_ABSOLUTE")
    parent = path.parent
    current = Path("/")
    for component in parent.parts[1:]:
        current /= component
        info = os.lstat(current)
        if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
            raise SafeError("UNSAFE_PARENT")
    info = os.stat(parent)
    if info.st_uid != os.getuid() or stat.S_IMODE(info.st_mode) & 0o077:
        raise SafeError("UNSAFE_PARENT")


def _read(path_text: str, *, private: bool = False) -> bytes:
    path = Path(path_text)
    _walk_parent(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags)
    try:
        info = os.fstat(fd)
        mode = stat.S_IMODE(info.st_mode)
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid()
                or info.st_nlink != 1 or (private and mode != 0o600)
                or (not private and mode & 0o022) or info.st_size > MAX_FILE):
            raise SafeError("UNSAFE_INPUT")
        chunks, remaining = [], MAX_FILE + 1
        while remaining:
            chunk = os.read(fd, min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk); remaining -= len(chunk)
        value = b"".join(chunks)
        if len(value) > MAX_FILE:
            raise SafeError("INPUT_TOO_LARGE")
        return value
    finally:
        os.close(fd)


def _write_new(path_text: str, value: bytes) -> str:
    path = Path(path_text)
    _walk_parent(path)
    if len(value) > MAX_FILE:
        raise SafeError("OUTPUT_TOO_LARGE")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_CLOEXEC", 0)
    fd = os.open(path, flags, 0o600)
    try:
        view = memoryview(value)
        while view:
            written = os.write(fd, view)
            view = view[written:]
        os.fsync(fd)
    except Exception:
        os.close(fd)
        try: os.unlink(path)
        except OSError: pass
        raise
    else:
        os.close(fd)
        directory = os.open(path.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
        try: os.fsync(directory)
        finally: os.close(directory)
    return hashlib.sha256(value).hexdigest()


def _pairs(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise SafeError("DUPLICATE_JSON_KEY")
        value[key] = item
    return value


def _json(path: str) -> dict:
    raw = _read(path)
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_pairs,
                           parse_float=lambda _: (_ for _ in ()).throw(SafeError("FLOAT_FORBIDDEN")))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SafeError("INVALID_JSON") from exc
    def inspect(item, depth=0):
        if depth > 32: raise SafeError("JSON_TOO_DEEP")
        if isinstance(item, str):
            if unicodedata.normalize("NFC", item) != item or any(unicodedata.category(c) in {"Cc", "Cf"} for c in item):
                raise SafeError("UNSAFE_UNICODE")
        elif isinstance(item, list):
            for child in item: inspect(child, depth + 1)
        elif isinstance(item, dict):
            for key, child in item.items(): inspect(key, depth + 1); inspect(child, depth + 1)
        elif type(item) not in (int, bool) and item is not None:
            raise SafeError("INVALID_JSON_TYPE")
    inspect(value)
    if not isinstance(value, dict): raise SafeError("INVALID_JSON_ROOT")
    return value


def _canonical(value: object) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def _evidence_bundle_sha256(*values: bytes) -> str:
    digest = hashlib.sha256(b"OBSIDIAN-B64-064A-EVIDENCE-BUNDLE\0V1\0")
    for value in values:
        digest.update(len(value).to_bytes(8, "big")); digest.update(value)
    return digest.hexdigest()


def _validate_v2_candidate(value: dict, *, issued_at: int) -> tuple[int, int]:
    authority = value.get("authority")
    source = value.get("sourceObservation")
    if (set(value) != V2_CANDIDATE_KEYS
            or value.get("schemaVersion") != "e0-3-bot-b5-3-064a-decision-candidate.v2"
            or value.get("project") != "obsidian-exchange" or value.get("route") != ROUTE
            or value.get("requestedDecision") != "ACCEPT_BOUNDED_EVIDENCE_ONLY"
            or value.get("effect") != "EVIDENCE_ACCEPTANCE_ONLY"
            or value.get("candidateStatus") != "AWAITING_NEW_AUTHENTICATED_DECISION"
            or not isinstance(source, dict)
            or set(source) != {"path", "sha256", "observedAt", "maximumAgeSecondsAtDecision"}
            or source.get("maximumAgeSecondsAtDecision") != 86400
            or not isinstance(source.get("sha256"), str) or len(source["sha256"]) != 64
            or any(c not in "0123456789abcdef" for c in source["sha256"])
            or not isinstance(authority, dict)
            or authority.get("freshnessCanInvalidate") is not True
            or set(authority) != {"freshnessCanInvalidate", "freshnessCanAuthorize",
                "ownerApprovalPresent", "independentReviewerApprovalPresent",
                "productionMutation", "productionExpandAuthorized", "deploymentAuthorized",
                "restartAuthorized", "cutoverAuthorized", "telegramDeliveryAuthorized",
                "ambiguousSendingDispositionAuthorized", "actionAllowed"}
            or any(item is not False for key, item in authority.items()
                   if key != "freshnessCanInvalidate")):
        raise SafeError("INVALID_DECISION_INPUT")
    try:
        observed = int(datetime.strptime(source["observedAt"], "%Y-%m-%dT%H:%M:%SZ")
                       .replace(tzinfo=timezone.utc).timestamp())
    except (KeyError, TypeError, ValueError) as exc:
        raise SafeError("INVALID_SOURCE_OBSERVATION_TIME") from exc
    source_expires = observed + source["maximumAgeSecondsAtDecision"]
    if not observed <= issued_at < source_expires:
        raise SafeError("SOURCE_OBSERVATION_NOT_CURRENT")
    return observed, source_expires


def _validate_candidate_evidence(value: dict, *, source_path: str,
                                 prior_state_path: str,
                                 active_deferral_path: str) -> None:
    source_raw = _read(source_path)
    prior_raw = _read(prior_state_path)
    deferral_raw = _read(active_deferral_path)
    source = _json(source_path)
    prior = _json(prior_state_path)
    deferral = _json(active_deferral_path)
    observation = value.get("sourceObservation", {})
    binding = value.get("sourceBinding")
    history = value.get("immutablePriorState")
    blockers = value.get("knownBlockers")
    dirty = source.get("dirtyData", {})
    counts = dirty.get("counts", {})
    equality = source.get("equality", {})
    source_authority = source.get("authority")
    source_keys = {"schemaVersion", "observedAt", "route", "status", "scope",
                   "source", "dirtyData", "archive", "restore", "equality",
                   "implementationSha256", "claimBoundary", "cleanup",
                   "authority", "remainingBlockers"}
    if "recordedAt" in source:
        source_keys |= {"recordedAt", "failClosedRehearsalNotes"}
    history_keys = ({"priorDecisionInputPath", "priorDecisionInputSha256",
                     "activeDeferralPath", "activeDeferralSha256",
                     "activeDeferralBindsPriorDecisionOnly", "activeDeferralRemainsRestrictive"}
                    if "priorCandidateSha256" not in history else
                    {"priorDecisionInputPath", "priorDecisionInputSha256",
                     "priorCandidatePath", "priorCandidateSha256",
                     "activeDeferralPath", "activeDeferralSha256",
                     "activeDeferralBindsPriorCandidateOnly", "activeDeferralRemainsRestrictive"})
    if (not isinstance(binding, dict) or not isinstance(history, dict)
            or not isinstance(blockers, list) or not blockers
            or any(not isinstance(item, str) or not item for item in blockers)
            or set(source) != source_keys
            or set(binding) != {"database", "postgresVersionNum", "sourceClusterSha256",
                "archiveSha256", "tableFingerprintSha256", "catalogFingerprintSha256",
                "catalogCoverageVersion"}
            or set(history) != history_keys
            or history.get("activeDeferralRemainsRestrictive") is not True
            or ("priorCandidateSha256" in history
                and history.get("activeDeferralBindsPriorCandidateOnly") is not True)
            or ("priorCandidateSha256" not in history
                and history.get("activeDeferralBindsPriorDecisionOnly") is not True)
            or Path(observation.get("path", "")).name != Path(source_path).name
            or observation.get("sha256") != hashlib.sha256(source_raw).hexdigest()
            or source.get("schemaVersion") != "e0-3-bot-b5-3-064a-production-source-refresh.v2"
            or source.get("route") != ROUTE
            or source.get("observedAt") != observation.get("observedAt")
            or source.get("status") != "BLOCKED_OWNER"
            or dirty.get("criterionStatus") != "BLOCKED"
            or dirty.get("privacy") != "NO_IDENTIFIERS_OR_PAYLOAD"
            or set(dirty) != {"criterionStatus", "privacy", "counts", "blockers", "observationDelta"}
            or set(counts) != {"total", "sent", "pending", "sending", "staleSending",
                "monteraAdmin", "activeMonteraAdmin", "invalidState", "invalidKind",
                "invalidLifecycle", "invalidActiveRecipientShape"}
            or not isinstance(counts, dict)
            or any(type(counts.get(key)) is not int or counts[key] < 0
                   for key in ("total", "sent", "pending", "sending", "staleSending"))
            or counts.get("total") != counts.get("sent", 0) + counts.get("pending", 0) + counts.get("sending", 0)
            or counts.get("staleSending", 0) > counts.get("sending", 0)
            or any(counts.get(key) != 0 for key in ("activeMonteraAdmin", "invalidState",
                "invalidKind", "invalidLifecycle", "invalidActiveRecipientShape"))
            or "LEGACY_SENDING_RECONCILED" not in dirty.get("blockers", [])
            or (counts.get("pending", 0) > 0 and "LEGACY_PENDING_DRAINED" not in dirty.get("blockers", []))
            or equality.get("tables") != 54 or equality.get("catalogSections") != 13
            or set(equality) != {"tables", "tableSourceAndRestoreSha256", "differentTables",
                "catalogCoverageVersion", "catalogSections", "catalogSourceAggregateSha256",
                "databaseLocalStatus", "differentDatabaseLocalSections",
                "separatelyReconstructedClusterGlobalStatus", "differentClusterGlobalSections",
                "sequenceRuntimeStateCompared"}
            or equality.get("databaseLocalStatus") != "MATCH"
            or equality.get("separatelyReconstructedClusterGlobalStatus") != "MATCH"
            or equality.get("differentTables") != []
            or equality.get("differentDatabaseLocalSections") != []
            or equality.get("differentClusterGlobalSections") != []
            or equality.get("sequenceRuntimeStateCompared") is not False
            or not isinstance(source_authority, dict)
            or set(source_authority) != {"observerOnly", "moneyWriter", "schemaWriter",
                "authenticatedAcceptancePresent", "productionMutationAuthorized",
                "productionExpandAuthorized", "ambiguousSendingDispositionAuthorized",
                "actionAllowed"}
            or source_authority.get("observerOnly") is not True
            or any(item is not False for key, item in source_authority.items()
                   if key != "observerOnly")
            or source.get("archive", {}).get("retained") is not False
            or set(source.get("cleanup", {})) != {"archiveAbsent", "manifestsAbsent",
                "containerAbsent", "tmpfsDestroyed"}
            or any(item is not True for item in source.get("cleanup", {}).values())
            or binding.get("database") != source.get("source", {}).get("database")
            or binding.get("postgresVersionNum") != source.get("source", {}).get("postgresVersionNum")
            or binding.get("sourceClusterSha256") != source.get("source", {}).get("sourceClusterSha256")
            or binding.get("archiveSha256") != source.get("archive", {}).get("sha256")
            or binding.get("tableFingerprintSha256") != source.get("equality", {}).get("tableSourceAndRestoreSha256")
            or binding.get("catalogFingerprintSha256") != source.get("equality", {}).get("catalogSourceAggregateSha256")
            or binding.get("catalogCoverageVersion") != source.get("equality", {}).get("catalogCoverageVersion")):
        raise SafeError("EVIDENCE_BINDING_INVALID")
    if (not any(f"{counts['sending']}_LEGACY_SENDING" in item for item in blockers)
            or (counts["pending"] > 0
                and not any(f"{counts['pending']}_PENDING" in item for item in blockers))
            or not any("ACCOUNTABLE_OWNER" in item for item in blockers)
            or not any("INDEPENDENT_REVIEWER" in item for item in blockers)
            or not any(all(term in item for term in
                           ("PRODUCTION_KEY_REGISTRY", "TRUSTED_TIME", "REVOCATION", "DURABLE_REPLAY"))
                       for item in blockers)):
        raise SafeError("BOUNDED_BLOCKERS_INVALID")
    prior_digest_field = "priorCandidateSha256" if "priorCandidateSha256" in history else "priorDecisionInputSha256"
    prior_path_field = "priorCandidatePath" if prior_digest_field == "priorCandidateSha256" else "priorDecisionInputPath"
    if (Path(history.get(prior_path_field, "")).name != Path(prior_state_path).name
            or history.get(prior_digest_field) != hashlib.sha256(prior_raw).hexdigest()
            or Path(history.get("activeDeferralPath", "")).name != Path(active_deferral_path).name
            or history.get("activeDeferralSha256") != hashlib.sha256(deferral_raw).hexdigest()
            or history.get("activeDeferralRemainsRestrictive") is not True
            or prior.get("route") != ROUTE or deferral.get("route") != ROUTE
            or deferral.get("status") != "BLOCKED_OWNER"):
        raise SafeError("PRIOR_STATE_BINDING_INVALID")
    if deferral.get("schemaVersion") == "e0-3-bot-b5-3-064a-owner-deferral.v3":
        authority = deferral.get("authority")
        deferral_safe = (deferral.get("route") == ROUTE
                         and Path(deferral.get("candidatePath", "")).name == Path(prior_state_path).name
                         and deferral.get("candidateSha256") == hashlib.sha256(prior_raw).hexdigest()
                         and deferral.get("sourceAuthentication") == "CONVERSATION_CONTEXT_NOT_AUTHENTICATED_SIGNATURE"
                         and deferral.get("decisionEffect") == "RESTRICTIVE_RE_DEFERRAL_ONLY"
                         and deferral.get("status") == "BLOCKED_OWNER"
                         and deferral.get("ownerDecisionContextPresent") is True
                         and deferral.get("authenticatedOwnerDecisionPresent") is False
                         and deferral.get("authenticatedEvidenceAcceptancePresent") is False
                         and deferral.get("independentReviewerAcceptancePresent") is False
                         and isinstance(authority, dict) and bool(authority)
                         and all(item is False for item in authority.values()))
    elif deferral.get("schemaVersion") == "e0-3-bot-b5-3-064a-owner-deferral.v2":
        deferral_safe = (deferral.get("candidateSha256") == hashlib.sha256(prior_raw).hexdigest()
                         and deferral.get("authenticatedEvidenceAcceptancePresent") is False
                         and deferral.get("independentReviewerAcceptancePresent") is False
                         and isinstance(deferral.get("authority"), dict)
                         and deferral["authority"]
                         and all(item is False for item in deferral["authority"].values()))
    else:
        deferral_safe = (deferral.get("schemaVersion") == "e0-3-bot-b5-3-064a-owner-deferral.v1"
                         and deferral.get("decisionInputSha256") == hashlib.sha256(prior_raw).hexdigest()
                         and deferral.get("authenticated064AAcceptancePresent") is False
                         and deferral.get("actionAllowed") is False)
    if not deferral_safe:
        raise SafeError("ACTIVE_DEFERRAL_INVALID")


def _passphrase(fd_value: int | None, confirm: bool = False) -> bytes:
    if fd_value is not None:
        raw = os.read(fd_value, 4097)
        if len(raw) > 4096: raise SafeError("PASSPHRASE_TOO_LONG")
        value = raw.rstrip(b"\r\n")
    else:
        value = getpass.getpass("Private-key passphrase: ").encode()
        if confirm and value != getpass.getpass("Repeat passphrase: ").encode():
            raise SafeError("PASSPHRASE_MISMATCH")
    if len(value) < 16: raise SafeError("PASSPHRASE_TOO_SHORT")
    return value


def _key_id(public_raw: bytes) -> str:
    return "b64k_" + hashlib.sha256(b"OBSIDIAN-B64-064A-ED25519\0" + public_raw).hexdigest()


def _load_private(path: str, passphrase_fd: int | None) -> Ed25519PrivateKey:
    key = serialization.load_pem_private_key(_read(path, private=True), password=_passphrase(passphrase_fd))
    if not isinstance(key, Ed25519PrivateKey): raise SafeError("WRONG_KEY_TYPE")
    return key


def _entry_from_public(value: dict) -> tuple[dict, bytes]:
    expected = {"schemaVersion", "keyId", "algorithm", "publicKeyEncoding", "publicKey",
                "identityId", "allowedRole", "trustDomain", "status", "trustEnvironment",
                "allowedRoutes", "allowedPhases"}
    if set(value) != expected or value["schemaVersion"] != "b64-064a-public-key-entry.v1" \
            or value["algorithm"] != "Ed25519" or value["publicKeyEncoding"] != "base64url-unpadded-raw32" \
            or value["allowedRole"] not in ROLES or value["status"] != "CANDIDATE" \
            or value["trustEnvironment"] != "CANDIDATE_OFFLINE" \
            or value["allowedRoutes"] != [ROUTE] \
            or value["allowedPhases"] != ["CATALOG_SECURITY_RESTORE_EVIDENCE"]:
        raise SafeError("INVALID_PUBLIC_ENTRY")
    try: raw = base64.urlsafe_b64decode(value["publicKey"] + "==")
    except Exception as exc: raise SafeError("INVALID_PUBLIC_KEY") from exc
    if len(raw) != 32 or value["keyId"] != _key_id(raw): raise SafeError("INVALID_PUBLIC_KEY")
    return value, raw


def command_generate(args) -> dict:
    if args.role not in ROLES or args.identity_id == args.trust_domain:
        raise SafeError("INVALID_IDENTITY_PROFILE")
    password = _passphrase(args.passphrase_fd, confirm=args.passphrase_fd is None)
    key = Ed25519PrivateKey.generate()
    private = key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                serialization.BestAvailableEncryption(password))
    public = key.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    key_id = _key_id(public)
    entry = {"schemaVersion":"b64-064a-public-key-entry.v1","keyId":key_id,
             "algorithm":"Ed25519","publicKeyEncoding":"base64url-unpadded-raw32",
             "publicKey":base64.urlsafe_b64encode(public).rstrip(b"=").decode(),
             "identityId":args.identity_id,"allowedRole":args.role,"trustDomain":args.trust_domain,
             "status":"CANDIDATE","trustEnvironment":"CANDIDATE_OFFLINE",
             "allowedRoutes":[ROUTE],"allowedPhases":["CATALOG_SECURITY_RESTORE_EVIDENCE"]}
    private_sha = _write_new(args.private_out, private)
    try: public_sha = _write_new(args.public_out, _canonical(entry) + b"\n")
    except Exception:
        os.unlink(args.private_out); raise
    return {"keyId":key_id,"privateFileSha256":private_sha,"publicEntrySha256":public_sha,
            "productionAuthority":False}


def command_keyring(args) -> dict:
    entries = [_entry_from_public(_json(args.reviewer_public))[0],
               _entry_from_public(_json(args.owner_public))[0]]
    by_role = {item["allowedRole"]: item for item in entries}
    if set(by_role) != ROLES or len({x["keyId"] for x in entries}) != 2 \
            or len({x["identityId"] for x in entries}) != 2 or len({x["trustDomain"] for x in entries}) != 2:
        raise SafeError("FOUR_EYES_NOT_INDEPENDENT")
    unsigned = {"schemaVersion":KEYRING_SCHEMA,"route":ROUTE,
                "trustEnvironment":"CANDIDATE_OFFLINE","keys":sorted(entries,key=lambda x:x["keyId"])}
    value = {**unsigned,"keyringSha256":hashlib.sha256(_canonical(unsigned)).hexdigest()}
    return {"keyringSha256":value["keyringSha256"],"outputSha256":_write_new(args.out,_canonical(value)+b"\n"),
            "productionAuthority":False}


def _load_keyring(path: str) -> tuple[dict, dict]:
    value = _json(path)
    if set(value) != {"schemaVersion","route","trustEnvironment","keys","keyringSha256"} \
            or value["schemaVersion"] != KEYRING_SCHEMA or value["route"] != ROUTE \
            or value["trustEnvironment"] != "CANDIDATE_OFFLINE" or not isinstance(value["keys"],list):
        raise SafeError("INVALID_KEYRING")
    unsigned = {k:value[k] for k in ("schemaVersion","route","trustEnvironment","keys")}
    if hashlib.sha256(_canonical(unsigned)).hexdigest() != value["keyringSha256"]: raise SafeError("KEYRING_DIGEST_MISMATCH")
    registry = {}
    for entry in value["keys"]:
        checked, raw = _entry_from_public(entry)
        registry[checked["keyId"]] = {"status":"ACTIVE","role":checked["allowedRole"],
            "identityId":checked["identityId"],"trustDomain":checked["trustDomain"],
            "trustEnvironment":"CANDIDATE_OFFLINE","publicRaw":raw}
    if len(registry) != 2: raise SafeError("INVALID_KEYRING")
    return value, registry


def command_statement(args) -> dict:
    decision_raw = _read(args.decision_input)
    decision = _json(args.decision_input)
    keyring, _ = _load_keyring(args.keyring)
    issued = int(args.issued_at); expires = int(args.expires_at)
    source_observed, source_expires = _validate_v2_candidate(decision, issued_at=issued)
    _validate_candidate_evidence(decision, source_path=args.source_observation,
                                 prior_state_path=args.prior_state,
                                 active_deferral_path=args.active_deferral)
    if not issued < expires <= issued + MAX_LIFETIME_SECONDS or expires > source_expires:
        raise SafeError("INVALID_STATEMENT_WINDOW")
    try:
        statement = build_statement(decision_input_sha256=hashlib.sha256(decision_raw).hexdigest(),
            evidence_bundle_sha256=_evidence_bundle_sha256(
                decision_raw, _read(args.source_observation), _read(args.prior_state),
                _read(args.active_deferral)),
            issued_at_epoch=issued,expires_at_epoch=expires,
            nonce=args.nonce or secrets.token_urlsafe(24),
            source_observed_at_epoch=source_observed,source_expires_at_epoch=source_expires)
    except ValueError as exc:
        raise SafeError("INVALID_STATEMENT_INPUT") from exc
    return {"statementSha256":statement["statementSha256"],"keyringSha256":keyring["keyringSha256"],
            "outputSha256":_write_new(args.out,_canonical(statement)+b"\n"),"productionAuthority":False}


def _profile(registry: dict, role: str) -> tuple[str, dict]:
    values = [(key_id,item) for key_id,item in registry.items() if item["role"]==role]
    if len(values)!=1: raise SafeError("INVALID_ROLE_PROFILE")
    return values[0]


def command_sign(args, role: str) -> dict:
    keyring, registry = _load_keyring(args.keyring); statement = _json(args.statement)
    key_id, profile = _profile(registry, role)
    private = _load_private(args.private_key,args.passphrase_fd)
    public = private.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)
    if public != profile["publicRaw"]: raise SafeError("PRIVATE_KEY_PROFILE_MISMATCH")
    signer=lambda expected,payload: private.sign(payload) if expected==key_id else (_ for _ in ()).throw(SafeError("KEY_MISMATCH"))
    common = dict(statement_sha256=statement["statementSha256"],key_id=key_id,
        identity_id=profile["identityId"],trust_domain=profile["trustDomain"],
        keyring_sha256=keyring["keyringSha256"],issued_at_epoch=statement["issuedAtEpoch"],
        expires_at_epoch=statement["expiresAtEpoch"],nonce=args.nonce or secrets.token_urlsafe(24),sign=signer)
    if role=="INDEPENDENT_REVIEWER": envelope=build_reviewer_envelope(**common)
    else: envelope=build_owner_envelope(review_envelope=_json(args.reviewer),**common)
    output=_canonical(envelope)+b"\n"
    return {"envelopeSha256":hashlib.sha256(_canonical(envelope)).hexdigest(),
            "outputSha256":_write_new(args.out,output),"productionAuthority":False}


def command_verify(args) -> dict:
    keyring, registry = _load_keyring(args.keyring); decision_raw=_read(args.decision_input)
    decision = _json(args.decision_input); statement = _json(args.statement)
    source_observed, source_expires = _validate_v2_candidate(
        decision, issued_at=statement.get("issuedAtEpoch", 0))
    _validate_candidate_evidence(decision, source_path=args.source_observation,
                                 prior_state_path=args.prior_state,
                                 active_deferral_path=args.active_deferral)
    expected_bundle = _evidence_bundle_sha256(
        decision_raw, _read(args.source_observation), _read(args.prior_state),
        _read(args.active_deferral))
    if statement.get("evidenceBundleSha256") != expected_bundle:
        raise SafeError("EVIDENCE_BUNDLE_DIGEST_MISMATCH")
    def verify(key_id,signature,payload): Ed25519PublicKey.from_public_bytes(registry[key_id]["publicRaw"]).verify(signature,payload)
    result=verify_decision(statement=statement,reviewer=_json(args.reviewer),owner=_json(args.owner),
        registry=registry,expected_keyring_sha256=keyring["keyringSha256"],
        current_input_sha256=hashlib.sha256(decision_raw).hexdigest(),now_epoch=int(args.now),
        verify_signature=verify,consume_pair=lambda *_:True,trust_environment="CANDIDATE_OFFLINE",
        expected_source_observed_at_epoch=source_observed,
        expected_source_expires_at_epoch=source_expires)
    return {**result,"replayProtectionVerified":False,"productionAuthority":False}


def parser() -> argparse.ArgumentParser:
    value=argparse.ArgumentParser(); commands=value.add_subparsers(dest="command",required=True)
    p=commands.add_parser("generate-key"); p.add_argument("--role",required=True); p.add_argument("--identity-id",required=True); p.add_argument("--trust-domain",required=True); p.add_argument("--private-out",required=True); p.add_argument("--public-out",required=True); p.add_argument("--passphrase-fd",type=int)
    p=commands.add_parser("build-keyring"); p.add_argument("--reviewer-public",required=True); p.add_argument("--owner-public",required=True); p.add_argument("--out",required=True)
    p=commands.add_parser("create-statement"); p.add_argument("--decision-input",required=True); p.add_argument("--source-observation",required=True); p.add_argument("--prior-state",required=True); p.add_argument("--active-deferral",required=True); p.add_argument("--keyring",required=True); p.add_argument("--issued-at",required=True); p.add_argument("--expires-at",required=True); p.add_argument("--nonce"); p.add_argument("--out",required=True)
    for name in ("sign-reviewer","sign-owner"):
        p=commands.add_parser(name); p.add_argument("--statement",required=True); p.add_argument("--keyring",required=True); p.add_argument("--private-key",required=True); p.add_argument("--passphrase-fd",type=int); p.add_argument("--nonce"); p.add_argument("--out",required=True)
        if name=="sign-owner": p.add_argument("--reviewer",required=True)
    p=commands.add_parser("verify"); p.add_argument("--decision-input",required=True); p.add_argument("--source-observation",required=True); p.add_argument("--prior-state",required=True); p.add_argument("--active-deferral",required=True); p.add_argument("--statement",required=True); p.add_argument("--reviewer",required=True); p.add_argument("--owner",required=True); p.add_argument("--keyring",required=True); p.add_argument("--now",required=True)
    return value


def main() -> int:
    os.umask(0o077)
    try:
        args=parser().parse_args()
        if args.command=="generate-key": result=command_generate(args)
        elif args.command=="build-keyring": result=command_keyring(args)
        elif args.command=="create-statement": result=command_statement(args)
        elif args.command=="sign-reviewer": result=command_sign(args,"INDEPENDENT_REVIEWER")
        elif args.command=="sign-owner": result=command_sign(args,"ACCOUNTABLE_OWNER")
        else: result=command_verify(args)
        _receipt("OK",**result); return 0
    except SafeError as exc:
        _receipt("ERROR",errorCode=str(exc),actionAllowed=False); return 3
    except Exception:
        _receipt("ERROR",errorCode="INTERNAL_ERROR",actionAllowed=False); return 70


if __name__=="__main__": raise SystemExit(main())
