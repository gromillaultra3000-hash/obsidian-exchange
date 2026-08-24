import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "relay"))
from core import order_access


def test_numeric_payment_proof_binds_order_user_and_time(monkeypatch):
    monkeypatch.setenv("RELAY_SECRET", "synthetic-order-access-secret")
    proof = order_access.issue(12, 34, now=1_000)
    assert order_access.verify(proof, 12, now=1_001) == 34
    assert order_access.verify(proof, 13, now=1_001) is None
    assert order_access.verify(proof, 12, now=1_000 + order_access.TTL_SECONDS + 1) is None
    assert order_access.verify(proof[:-1] + ("0" if proof[-1] != "0" else "1"), 12,
                               now=1_001) is None


def test_numeric_payment_proof_fails_closed_without_real_secret(monkeypatch):
    monkeypatch.delenv("RELAY_SECRET", raising=False)
    assert order_access.issue(1, 2, now=1_000) is None
    monkeypatch.setenv("RELAY_SECRET", "fallback")
    assert order_access.issue(1, 2, now=1_000) is None
    assert order_access.verify("", 1, now=1_000) is None
