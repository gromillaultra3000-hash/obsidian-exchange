"""Metadata-only E5 provenance and corpus-manifest policy checks.

This test deliberately uses only the Python standard library. It validates
cross-field invariants that the JSON Schema cannot express, without parsing or
executing any external source, fixture key, signature, or verifier.
"""

from __future__ import annotations

import hashlib
import json
import re
import unittest
from pathlib import Path
from urllib.parse import urlparse


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/tests/fixtures"
HEX64 = re.compile(r"^[0-9a-f]{64}$")
HEX40 = re.compile(r"^[0-9a-f]{40}$")


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _require_sha256(value: object, label: str) -> None:
    _require(isinstance(value, str) and HEX64.fullmatch(value) is not None, label)


def validate_source_provenance(provenance: dict) -> None:
    _require(
        provenance.get("schema") == "native-wallet-attestation-source-provenance.v1",
        "unexpected provenance schema",
    )
    _require(provenance.get("fixtures_vendored") is True, "fixture policy drift")
    for flag in ("dependencies_installed", "verification_implemented", "production_action_allowed"):
        _require(provenance.get(flag) is False, f"authority flag is enabled: {flag}")

    sources = provenance.get("sources")
    _require(isinstance(sources, list) and len(sources) == 5, "source count drift")
    by_id: dict[str, dict] = {}
    for source in sources:
        _require(isinstance(source, dict), "source entry is not an object")
        source_id = source.get("id")
        _require(isinstance(source_id, str) and source_id not in by_id, "source ID is not unique")
        revision = source.get("revision")
        _require(isinstance(revision, str) and HEX40.fullmatch(revision) is not None, "revision drift")
        _require(source.get("vendored") is False, "upstream source was vendored")
        _require_sha256(source.get("sha256"), "source hash drift")
        url = urlparse(str(source.get("url", "")))
        _require(
            url.scheme == "https"
            and url.hostname == "raw.githubusercontent.com"
            and not url.query
            and not url.fragment,
            "source URL is not immutable raw HTTPS",
        )
        path = source.get("path")
        _require(isinstance(path, str) and path and url.path.endswith(f"/{revision}/{path}"), "URL/path drift")
        by_id[source_id] = source

    derived = provenance.get("derived_fixtures")
    _require(isinstance(derived, list) and len(derived) == 1, "derived fixture count drift")
    fixture = derived[0]
    _require(fixture.get("derived_from_source_id") in by_id, "unknown derived source")
    fixture_relpath = fixture.get("path", "")
    _require(
        isinstance(fixture_relpath, str)
        and fixture_relpath
        and not fixture_relpath.startswith("/")
        and ".." not in Path(fixture_relpath).parts,
        "derived fixture path escapes fixture root",
    )
    fixture_path = FIXTURES / fixture_relpath
    _require(fixture_path.is_file(), "derived fixture is absent")
    actual_hash = hashlib.sha256(fixture_path.read_bytes()).hexdigest()
    _require(fixture.get("sha256") == actual_hash, "derived fixture hash drift")
    for flag in (
        "contains_signature",
        "contains_key_material",
        "official_standalone_conformance_vector",
    ):
        _require(fixture.get(flag) is False, f"derived fixture flag drift: {flag}")
    _require(fixture.get("vendored") is True, "derived fixture must be vendored")

    source = by_id[fixture["derived_from_source_id"]]
    pae = _read_json(FIXTURES / "dsse-pae-reference-v1.json")
    derived_from = pae.get("derived_from", {})
    for field, source_field in (
        ("revision", "revision"),
        ("path", "path"),
        ("source_sha256", "sha256"),
        ("license", "license"),
    ):
        _require(derived_from.get(field) == source[source_field], f"PAE provenance drift: {field}")
    for flag in (
        "official_standalone_conformance_vector",
        "contains_signature",
        "contains_public_key",
        "contains_private_or_signing_key",
        "verification_implemented",
        "production_action_allowed",
    ):
        _require(pae.get(flag) is False, f"PAE fixture flag drift: {flag}")


def validate_manifest_policy(manifest: dict) -> None:
    _require(
        manifest.get("schema") == "native-wallet-webauthn-rp-corpus-manifest.v1",
        "unexpected corpus schema",
    )
    _require(manifest.get("expectations_sealed_before_results") is True, "expectations are not sealed")
    for flag in ("official_conformance_claimed", "authentication_allowed", "production_action_allowed"):
        _require(manifest.get(flag) is False, f"corpus authority flag is enabled: {flag}")
    _require_sha256(manifest.get("corpus_sha256"), "corpus hash drift")

    cases = manifest.get("cases")
    _require(isinstance(cases, list) and len(cases) >= 24, "corpus case count drift")
    case_ids: set[str] = set()
    for case in cases:
        _require(isinstance(case, dict), "case is not an object")
        case_id = case.get("id")
        _require(isinstance(case_id, str) and case_id not in case_ids, "case ID is not unique")
        case_ids.add(case_id)
        _require(case.get("expected") in {"ACCEPT_NON_AUTHORITATIVE", "REJECT"}, "case expectation drift")
        _require(case.get("contains_private_key") is False, "private fixture key claimed")
        generator = case.get("generator")
        _require(isinstance(generator, dict) and generator.get("network_disabled") is True, "generator is not offline")
        _require(isinstance(generator.get("revision"), str) and HEX40.fullmatch(generator["revision"]), "generator revision drift")
        _require_sha256(generator.get("toolchain_sha256"), "toolchain hash drift")
        _require_sha256(case.get("context_sha256"), "context hash drift")
        _require_sha256(case.get("enrollment_sha256"), "enrollment hash drift")
        _require_sha256(case.get("artifact_sha256"), "artifact hash drift")
        _require_sha256(case.get("recipe_sha256"), "recipe hash drift")

    reviewers = manifest.get("reviewers")
    _require(isinstance(reviewers, list) and len(reviewers) == 2, "reviewer count drift")
    reviewer_ids = [item.get("reviewer_id") for item in reviewers]
    reviewer_domains = [item.get("administrative_domain") for item in reviewers]
    _require(len(set(reviewer_ids)) == 2, "reviewer IDs are not distinct")
    _require(len(set(reviewer_domains)) == 2, "reviewer domains are not independent")
    for reviewer in reviewers:
        _require(reviewer.get("generator_author") is False, "generator author is a reviewer")
        _require_sha256(reviewer.get("review_sha256"), "review hash drift")

    results = manifest.get("implementation_results")
    _require(isinstance(results, list) and len(results) == 2, "implementation result count drift")
    implementations = [item.get("implementation") for item in results]
    result_domains = [item.get("administrative_domain") for item in results]
    _require(len(set(implementations)) == 2, "implementation results are not independent")
    _require(len(set(result_domains)) == 2, "implementation domains are not independent")
    for result in results:
        _require(result.get("corpus_sha256") == manifest["corpus_sha256"], "result corpus hash drift")
        _require_sha256(result.get("result_sha256"), "result hash drift")


def valid_manifest() -> dict:
    digest = "a" * 64
    return {
        "schema": "native-wallet-webauthn-rp-corpus-manifest.v1",
        "corpus_sha256": digest,
        "expectations_sealed_before_results": True,
        "cases": [
            {
                "id": f"CASE_{index:02d}",
                "expected": "REJECT" if index else "ACCEPT_NON_AUTHORITATIVE",
                "mutation_dimension": "single_field",
                "standards_clauses": ["synthetic"],
                "rationale": "metadata-only test case",
                "context_sha256": digest,
                "enrollment_sha256": digest,
                "artifact_sha256": digest,
                "generator": {
                    "name": "offline-generator",
                    "version": "1",
                    "revision": "b" * 40,
                    "toolchain_sha256": digest,
                    "network_disabled": True,
                },
                "recipe_sha256": digest,
                "contains_private_key": False,
            }
            for index in range(24)
        ],
        "reviewers": [
            {"reviewer_id": "reviewer_a", "administrative_domain": "domain_a", "generator_author": False, "review_sha256": digest},
            {"reviewer_id": "reviewer_b", "administrative_domain": "domain_b", "generator_author": False, "review_sha256": digest},
        ],
        "implementation_results": [
            {"implementation": "oracle_a", "administrative_domain": "impl_domain_a", "corpus_sha256": digest, "result_sha256": digest},
            {"implementation": "oracle_b", "administrative_domain": "impl_domain_b", "corpus_sha256": digest, "result_sha256": digest},
        ],
        "agreement": False,
        "official_conformance_claimed": False,
        "authentication_allowed": False,
        "production_action_allowed": False,
    }


class E5ProvenancePolicyTests(unittest.TestCase):
    def test_pinned_source_and_derived_fixture_provenance(self) -> None:
        validate_source_provenance(_read_json(FIXTURES / "attestation-source-provenance.json"))

    def test_schema_and_metadata_policy_are_closed(self) -> None:
        schema = _read_json(FIXTURES / "webauthn-corpus-manifest.schema.json")
        self.assertFalse(schema["additionalProperties"])
        for name in ("case", "reviewer", "result"):
            self.assertFalse(schema["$defs"][name]["additionalProperties"])
        self.assertFalse(schema["$defs"]["case"]["properties"]["generator"]["additionalProperties"])
        validate_manifest_policy(valid_manifest())

    def test_cross_field_mutations_fail_closed(self) -> None:
        mutations = []
        value = valid_manifest()
        value["cases"][1]["id"] = value["cases"][0]["id"]
        mutations.append(value)
        value = valid_manifest()
        value["reviewers"][1]["administrative_domain"] = value["reviewers"][0]["administrative_domain"]
        mutations.append(value)
        value = valid_manifest()
        value["implementation_results"][1]["corpus_sha256"] = "c" * 64
        mutations.append(value)
        value = valid_manifest()
        value["cases"][0]["contains_private_key"] = True
        mutations.append(value)
        for mutation in mutations:
            with self.assertRaises(ValueError):
                validate_manifest_policy(mutation)


if __name__ == "__main__":
    unittest.main()
