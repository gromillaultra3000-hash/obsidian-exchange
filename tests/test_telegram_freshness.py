import importlib.util
from pathlib import Path


PATH = Path("/root/relay/core/telegram_freshness.py")
SPEC = importlib.util.spec_from_file_location("telegram_freshness", PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_missing_invalid_stale_and_future_auth_dates_fail_closed():
    now = 1_786_366_800
    assert MODULE.valid_auth_date(now, max_age=300, now=now)
    assert MODULE.valid_auth_date(now - 300, max_age=300, now=now)
    for value in (None, "", "bad", 0, now - 301, now + 31):
        assert not MODULE.valid_auth_date(value, max_age=300, now=now)
