"""Metadata-only audit of the isolated E5 attestation rehearsal boundary.

The rehearsal crates are deliberately not native-wallet dependencies. These
checks bind their local manifests and lockfiles to RESULTS.json without
building, importing or executing any external source from Python.
"""

from __future__ import annotations

import hashlib
import json
import re
import tomllib
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REHEARSAL_ROOT = ROOT / "native-wallet/rehearsals/attestation-dependencies"
NATIVE_MANIFEST = ROOT / "native-wallet/Cargo.toml"
NATIVE_LOCK = ROOT / "native-wallet/Cargo.lock"

EXPECTED = {
    "human-rp": {
        "package": "attestation-human-rp-dependency-rehearsal",
        "direct": {"webauthn-rs": "=0.5.5"},
        "registry_packages": 116,
        "host_check": "BLOCKED_NATIVE_OPENSSL_DISCOVERY",
        "selected_for_integration": False,
    },
    "automated-minimal": {
        "package": "attestation-automated-minimal-dependency-rehearsal",
        "direct": {
            "base64": "=0.23.1",
            "ed25519-dalek": "=3.0.0",
            "serde": "=1.0.228",
            "serde_json": "=1.0.145",
        },
        "registry_packages": 36,
        "host_check": "PASS",
        "selected_for_integration": False,
    },
    "automated-with-schema": {
        "package": "attestation-automated-schema-dependency-rehearsal",
        "direct": {
            "base64": "=0.23.1",
            "ed25519-dalek": "=3.0.0",
            "in_toto_attestation": "=0.1.0",
            "serde": "=1.0.228",
            "serde_json": "=1.0.145",
        },
        "registry_packages": 83,
        "host_check": "PASS",
        "selected_for_integration": False,
    },
}


def _json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _cargo(path: Path) -> dict:
    return tomllib.loads(path.read_text(encoding="utf-8"))


class E5AttestationRehearsalBoundaryTests(unittest.TestCase):
    def test_results_bind_exact_pinned_lock_graphs(self) -> None:
        results = _json(REHEARSAL_ROOT / "RESULTS.json")
        self.assertEqual(results["schema"], "native-wallet-attestation-dependency-rehearsal.v1")
        self.assertEqual(results["rust"], "1.97.1")
        self.assertEqual(results["native_workspace_changed"], False)
        self.assertEqual(results["verifier_implemented"], False)
        self.assertEqual(results["trust_roots_installed"], False)
        self.assertEqual(results["production_action_allowed"], False)

        profiles = {profile["id"]: profile for profile in results["profiles"]}
        self.assertEqual(set(profiles), set(EXPECTED))
        for profile_id, expected in EXPECTED.items():
            profile = profiles[profile_id]
            rehearsal = REHEARSAL_ROOT / profile_id
            self.assertEqual(profile["lock_sha256"], _sha256(rehearsal / "Cargo.lock"))
            self.assertEqual(profile["registry_packages"], expected["registry_packages"])
            self.assertEqual(profile["host_check"], expected["host_check"])
            self.assertEqual(profile["selected_for_integration"], expected["selected_for_integration"])

            lock = _cargo(rehearsal / "Cargo.lock")
            packages = lock["package"]
            self.assertEqual(
                sum(item.get("source", "").startswith("registry+") for item in packages),
                expected["registry_packages"],
            )
            roots = [item for item in packages if "source" not in item]
            self.assertEqual(len(roots), 1)
            self.assertEqual(roots[0]["name"], expected["package"])
            self.assertEqual(roots[0]["version"], "0.0.0")
            self.assertTrue(all(item.get("source", "").startswith("registry+") for item in packages if item not in roots))

    def test_rehearsal_manifests_are_standalone_and_exactly_pinned(self) -> None:
        for profile_id, expected in EXPECTED.items():
            rehearsal = REHEARSAL_ROOT / profile_id
            manifest_text = (rehearsal / "Cargo.toml").read_text(encoding="utf-8")
            manifest = _cargo(rehearsal / "Cargo.toml")
            self.assertEqual(manifest["package"]["name"], expected["package"])
            self.assertEqual(manifest["package"]["version"], "0.0.0")
            self.assertFalse(manifest["package"]["publish"])
            self.assertEqual(manifest["workspace"], {})
            self.assertNotIn("path =", manifest_text)
            self.assertNotIn("git =", manifest_text)

            dependencies = manifest["dependencies"]
            self.assertEqual(set(dependencies), set(expected["direct"]))
            for name, version in expected["direct"].items():
                dependency = dependencies[name]
                if isinstance(dependency, dict):
                    self.assertEqual(dependency["version"], version)
                    self.assertFalse(dependency["default-features"])
                else:
                    self.assertEqual(name, "in_toto_attestation")
                    self.assertEqual(dependency, version)

            results = _json(REHEARSAL_ROOT / "RESULTS.json")
            profile = next(item for item in results["profiles"] if item["id"] == profile_id)
            lock = _cargo(rehearsal / "Cargo.lock")
            root_package = next(item for item in lock["package"] if item["name"] == expected["package"])
            self.assertEqual(set(root_package["dependencies"]), set(expected["direct"]))
            self.assertEqual(profile["direct_dependencies"], [f"{name}{version}" for name, version in expected["direct"].items()])

    def test_minimal_source_remains_non_authoritative_and_outside_native_workspace(self) -> None:
        source = (REHEARSAL_ROOT / "automated-minimal/src/lib.rs").read_text(encoding="utf-8")
        self.assertIn("pub const VERIFIER_IMPLEMENTED: bool = false;", source)
        for symbol in (
            "pub fn parse_envelope",
            "pub fn decode_payload_exact",
            "pub fn decode_signature_exact",
            "pub fn construct_pae",
            "pub fn parse_verified_payload",
            "pub fn validate_verified_statement",
        ):
            self.assertIn(symbol, source)
        self.assertGreaterEqual(source.count("#[serde(deny_unknown_fields)]"), 9)
        self.assertNotRegex(source, r"(?m)^\s*use .*ed25519")
        self.assertNotRegex(source, r"(?m)^\s*use .*\b(std::net|std::process|tokio|reqwest)\b")

        native_manifest = _cargo(NATIVE_MANIFEST)
        self.assertEqual(native_manifest["workspace"]["members"], ["crates/wallet-core", "crates/wallet-ffi"])
        native_lock = _cargo(NATIVE_LOCK)
        native_names = {package["name"] for package in native_lock["package"]}
        for expected in EXPECTED.values():
            self.assertNotIn(expected["package"], native_names)
        self.assertNotIn("webauthn-rs", native_names)
        self.assertNotIn("in_toto_attestation", native_names)


if __name__ == "__main__":
    unittest.main()
