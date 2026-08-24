import hashlib
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOC = ROOT / "docs/b64-064a-offline-signing-v4.md"


def test_v4_handoff_binds_current_candidate_and_v3_prior_context():
    text = DOC.read_text()
    expected = {
        "docs/e0-3-bot-b5-3-064a-decision-candidate.v4.json":
            "32d54d2bfaf555c7d795cc70b8b92561d7a6d9a19262eb1089eb3611aafd2316",
        "docs/e0-3-bot-b5-3-064a-production-source-refresh.v4.json":
            "99531224f6eac8d13ce07b14fdf6408f333fca2a10426e7876613ce3da812a80",
        "docs/e0-3-bot-b5-3-064a-decision-candidate.v3.json":
            "771ce159032de810d8b09731be109af6a2bb317fc1b8b6e2f5a0d3fff9a08ddf",
        "docs/e0-3-bot-b5-3-064a-owner-deferral.v3.json":
            "c1cf8375efe84ce4a77302263f3450d661f732ee88dd30164dc711bc94a2f7e3",
    }
    for path, digest in expected.items():
        assert path in text and digest in text
        assert hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == digest
    assert "two genuinely independent offline devices" in text
    assert "does not satisfy this requirement" in text
    assert "--decision-input /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v4.json" in text
    assert "--prior-state /absolute/coord/e0-3-bot-b5-3-064a-decision-candidate.v3.json" in text
    assert "--active-deferral /absolute/coord/e0-3-bot-b5-3-064a-owner-deferral.v3.json" in text
    for command in ("generate-key", "build-keyring", "sign-reviewer", "sign-owner"):
        assert command in text


def test_v4_handoff_is_fail_closed_and_secret_free():
    text = DOC.read_text()
    for phrase in (
        "productionExpandAuthorized:false",
        "cutoverAuthorized:false",
        "actionAllowed:false",
        "replayProtectionVerified:false",
        "Private keys",
        "passphrases",
    ):
        assert phrase in text
    assert not re.search(r"password\s*[:=]", text, re.IGNORECASE)
    assert "BEGIN OPENSSH PRIVATE KEY" not in text
    assert "postgresql://" not in text


if __name__ == "__main__":
    for name in sorted(globals()):
        if name.startswith("test_"):
            globals()[name]()
    print("064A_V4_HANDOFF_STATIC_PASS")
