import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "relay/services/payout_circuit.py",
    "relay/services/payout_guard.py",
    "relay/services/conversion_intel.py",
    "relay/services/evidence.py",
    "relay/services/smart_router.py",
    "relay-fastapi/pay_handler.py",
]


def test_active_modules_do_not_pin_production_db():
    for rel in FILES:
        text = (ROOT / rel).read_text("utf-8")
        ast.parse(text, filename=rel)
        assert 'DB_PATH = "/root/exchange.db"' not in text
        assert "DB_PATH = '/root/exchange.db'" not in text
        assert "os.getenv" in text, rel


def test_pay_template_follows_checkout():
    text = (ROOT / "relay-fastapi/pay_handler.py").read_text("utf-8")
    assert 'Path(__file__).resolve().parents[1] / "relay"' in text
    assert 'template_path = "/root/' not in text


if __name__ == "__main__":
    test_active_modules_do_not_pin_production_db()
    test_pay_template_follows_checkout()
    print("runtime path tests: OK")
