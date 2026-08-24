import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _provider_module():
    path = ROOT / "relay/providers/swapuz.py"
    sys.path.insert(0, str(ROOT / "relay"))
    spec = importlib.util.spec_from_file_location("swapuz_status_under_test", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unknown_and_provider_drift_fail_closed():
    provider = _provider_module()
    assert provider.safe_swapuz_transition("waiting", None) is None
    assert provider.safe_swapuz_transition("waiting", "unknown") is None
    assert provider.safe_swapuz_transition("waiting", "status_99") is None


def test_terminal_status_cannot_regress():
    provider = _provider_module()
    for terminal in provider.SWAPUZ_TERMINAL_STATUSES:
        assert provider.safe_swapuz_transition(terminal, "waiting") is None
        assert provider.safe_swapuz_transition(terminal, "confirming") is None
        assert provider.safe_swapuz_transition(terminal, terminal) == terminal


def test_only_allowlisted_forward_progress_is_accepted():
    provider = _provider_module()
    assert provider.safe_swapuz_transition("waiting", "confirming") == "confirming"
    assert provider.safe_swapuz_transition("confirming", "sending") == "sending"
    assert provider.safe_swapuz_transition("sending", "finished") == "finished"
    assert provider.safe_swapuz_transition("sending", "confirming") is None


def test_provider_status_decoder_requires_exact_documented_integer_codes():
    provider = _provider_module()
    expected = {
        0: "waiting", 1: "confirming", 2: "confirming", 3: "exchanging",
        4: "sending", 5: "sending", 6: "finished", 10: "expired",
    }
    for code, status in expected.items():
        assert provider.decode_swapuz_status(code) == status
    for malformed in (None, True, False, 1.0, "1", -1, 7, 99, [], {}):
        assert provider.decode_swapuz_status(malformed) is None


def test_all_swapuz_runtime_callers_use_transition_guard():
    relay = (ROOT / "relay-fastapi/main.py").read_text()
    bot = (ROOT / "bot/main_bot.py").read_text()
    page = relay[relay.index("async def swap_page"):relay.index("@app.post(\"/trocador/webhook\")")]
    monitor = bot[bot.index("async def swap_status_monitor"):bot.index("@router.message(Command(\"history\"))", bot.index("async def swap_status_monitor"))]
    assert "from providers.swapuz import SwapUzProvider, safe_swapuz_transition" in monitor
    assert "safe_swapuz_transition(status, info.get('status'))" in page
    assert "safe_swapuz_transition(old_status, info.get('status'))" in monitor
    assert "if not new_status or new_status == old_status:" in monitor
