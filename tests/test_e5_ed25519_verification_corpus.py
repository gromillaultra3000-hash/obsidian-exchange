import hashlib
import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
FIXTURES = (
    ROOT
    / "native-wallet"
    / "rehearsals"
    / "attestation-dependencies"
    / "automated-minimal"
    / "tests"
    / "fixtures"
)
CORPUS_PATH = FIXTURES / "ed25519-verification-corpus-v1.json"
PROVENANCE_PATH = FIXTURES / "ed25519-verification-corpus-v1.provenance.json"


def _load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def test_public_corpus_is_byte_pinned_and_has_no_secret_material():
    corpus_bytes = CORPUS_PATH.read_bytes()
    corpus = json.loads(corpus_bytes)
    provenance = _load(PROVENANCE_PATH)

    assert hashlib.sha256(corpus_bytes).hexdigest() == provenance["corpus_sha256"]
    assert corpus["schema"] == "native-wallet-ed25519-verification-corpus.v1"
    assert corpus["source"]["document"] == "RFC 8032"
    assert corpus["source"]["section"] == "7.1"
    assert corpus["source"]["vector"] == "TEST 2"
    assert corpus["source"]["secret_fields_copied"] is False
    assert corpus["contains_private_key"] is False
    assert corpus["contains_seed"] is False
    assert provenance["private_material_present"] is False

    serialized_keys = set()

    def collect_keys(value):
        if isinstance(value, dict):
            for key, child in value.items():
                serialized_keys.add(key.lower())
                collect_keys(child)
        elif isinstance(value, list):
            for child in value:
                collect_keys(child)

    collect_keys(corpus)
    assert not ({"private_key", "private_key_hex", "secret_key", "secret_key_hex", "seed_hex"} & serialized_keys)


def test_baseline_shape_and_mutations_are_closed_and_single_dimension():
    corpus = _load(CORPUS_PATH)
    baseline = corpus["baseline"]
    assert baseline["algorithm"] == "Ed25519"
    assert len(bytes.fromhex(baseline["public_key_hex"])) == 32
    assert bytes.fromhex(baseline["message_hex"]) == b"r"
    assert len(bytes.fromhex(baseline["signature_hex"])) == 64
    assert baseline["expected"] == "VALID"

    allowed_fields = {"public_key_hex", "message_hex", "signature_hex"}
    allowed_operations = {"xor-byte", "replace-all-bytes", "truncate-bytes"}
    ids = set()
    for mutation in corpus["mutations"]:
        assert mutation["id"] not in ids
        ids.add(mutation["id"])
        assert mutation["field"] in allowed_fields
        assert mutation["operation"] in allowed_operations
        assert mutation["expected"] == "INVALID"
        assert isinstance(mutation["operand"], int)
        assert 0 <= mutation["operand"] <= 255
        assert set(mutation) <= {"id", "field", "operation", "offset", "operand", "expected"}

    assert ids == {
        "public-key-bit-flip",
        "message-bit-flip",
        "signature-r-bit-flip",
        "signature-s-bit-flip",
        "public-key-all-zero",
        "public-key-truncated",
        "signature-truncated",
    }


def test_corpus_cannot_claim_verification_or_runtime_authority():
    corpus = _load(CORPUS_PATH)
    provenance = _load(PROVENANCE_PATH)
    assert corpus["verification_executed"] is False
    assert corpus["authoritative_success"] is False
    assert corpus["runtime_integration_allowed"] is False
    assert provenance["review_state"] == "PINNED_FOR_INDEPENDENT_REVIEW"
    assert provenance["crypto_call_allowed"] is False
    assert provenance["runtime_integration_allowed"] is False
