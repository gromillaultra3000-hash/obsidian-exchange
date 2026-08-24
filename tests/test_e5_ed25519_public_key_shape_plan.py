import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "native-wallet/rehearsals/attestation-dependencies/automated-minimal/tests/fixtures"
SHAPE_PATH = FIXTURES / "ed25519-corpus-review-public-key-shape-policy-v1.json"
PLAN_PATH = FIXTURES / "ed25519-corpus-review-public-key-fixture-provenance-plan-v1.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_ed25519_shape_requires_strict_point_and_verification_semantics():
    policy = _load(SHAPE_PATH)["ed25519_verifying_key"]
    assert policy["exact_bytes"] == 32
    checks = " ".join(policy["required_checks"])
    assert "canonical compressed-y" in checks
    assert "on curve" in checks
    assert "torsion-free and not small-order" in checks
    assert "non-canonical scalar and weak-key" in checks
    assert "acceptance based only on length or digest" in policy["forbidden"]


def test_cose_shape_is_exact_deterministic_public_es256_key():
    policy = _load(SHAPE_PATH)["webauthn_es256_cose_key"]
    assert policy["maximum_bytes"] == 256
    assert policy["exact_map_entries"] == 5
    labels = policy["exact_labels"]
    assert labels["1"]["value"] == 2
    assert labels["3"]["value"] == -7
    assert labels["-1"]["value"] == 1
    assert labels["-2"]["byte_string_length"] == labels["-3"]["byte_string_length"] == 32
    checks = " ".join(policy["required_checks"])
    assert "deterministic CBOR" in checks
    assert "finite on-curve NIST P-256 point" in checks


def test_validation_order_selects_snapshot_and_digest_before_parse_or_crypto():
    policy = _load(SHAPE_PATH)
    order = policy["validation_order"]
    assert order[:3] == [
        "consumer selects active snapshot",
        "bounded exact byte length",
        "snapshot byte digest equality",
    ]
    assert order.index("strict candidate-specific parse and semantic point checks") < order.index("symbolic signature outcome")


def test_fixture_plan_allows_only_public_verification_fields():
    plan = _load(PLAN_PATH)
    classes = {item["id"]: item for item in plan["fixture_classes"]}
    assert set(classes) == {"ed25519_public_verification_keys", "webauthn_es256_cose_public_keys"}
    assert "public_key_hex" in classes["ed25519_public_verification_keys"]["allowed_fields"]
    assert "cose_key_hex" in classes["webauthn_es256_cose_public_keys"]["allowed_fields"]
    serialized = json.dumps(classes, sort_keys=True)
    for forbidden in ["private_key", "secret_scalar", "seed_hex", "credential_cookie"]:
        assert forbidden not in serialized


def test_mutation_plan_covers_encoding_points_algorithms_and_signatures():
    plan = _load(PLAN_PATH)
    classes = {item["id"]: item for item in plan["fixture_classes"]}
    ed = " ".join(classes["ed25519_public_verification_keys"]["required_mutations"])
    cose = " ".join(classes["webauthn_es256_cose_public_keys"]["required_mutations"])
    assert "small-order public point" in ed
    assert "S non-canonical" in ed
    assert "duplicate COSE label" in cose
    assert "off-curve point" in cose
    assert "wrong kty alg or curve" in cose


def test_import_requires_provenance_license_and_two_independent_reviews():
    plan = _load(PLAN_PATH)
    metadata = " ".join(plan["per_fixture_required_metadata"])
    assert "upstream URL and immutable revision" in metadata
    assert "license or redistribution reference" in metadata
    assert "independent reviewer A" in metadata
    assert "independent reviewer B" in metadata
    reviews = " ".join(plan["review_requirements"])
    assert "distinct identity and trust domains" in reviews
    assert "no seed private scalar recovery secret" in reviews


def test_no_fixture_parser_key_or_crypto_is_present():
    shape = _load(SHAPE_PATH)
    plan = _load(PLAN_PATH)
    for field in ["ed25519_parser_implemented", "cose_parser_implemented", "elliptic_curve_checks_implemented", "public_key_bytes_present", "private_material_present", "crypto_call_allowed", "checkpoint_authenticated", "runtime_integration_allowed"]:
        assert shape[field] is False
    for field in ["sources_selected", "licenses_reviewed", "independent_reviews_present", "fixture_bytes_imported", "parser_dependency_selected", "crypto_call_allowed", "runtime_integration_allowed"]:
        assert plan[field] is False
