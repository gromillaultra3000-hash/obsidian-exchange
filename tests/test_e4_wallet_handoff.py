"""Synthetic SDK ownership races; exact extracted production JavaScript, no real signing."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name("e4_wallet_handoff.cjs")
WEBAPP = Path(os.environ.get("E4_WEBAPP_SOURCE", ROOT / "relay/webapp.html"))


def run_case(scenario, **parameters):
    node = shutil.which("node")
    assert node, "Node required for wallet handoff acceptance"
    result = subprocess.run([node, str(RUNNER), str(WEBAPP), scenario, json.dumps(parameters)],
                            cwd=ROOT, text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "HANDOFF_CASE_COMPLETE" in result.stdout, "scenario exited with unresolved promise"


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("replacement", ["transfer", "payment"])
@pytest.mark.parametrize("boundary", ["cancel", "close", "escape", "expiry"])
@pytest.mark.parametrize("outcome", ["resolve", "reject"])
def test_pending_sdk_excludes_second_handoff(action, replacement, boundary, outcome):
    run_case("pending", action=action, replacement=replacement, boundary=boundary, outcome=outcome)


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("replacement", ["transfer", "payment"])
def test_synchronous_sdk_throw_requires_reconciliation_for_fresh_review(action, replacement):
    run_case("sync_throw", action=action, replacement=replacement)


@pytest.mark.parametrize("replacement", ["transfer", "payment"])
def test_signed_marker_pending_is_outside_sdk_lock(replacement):
    run_case("followup", replacement=replacement)


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("replacement", ["transfer", "payment"])
def test_stale_callback_cannot_sign_during_fresh_preparation(action, replacement):
    run_case("late_json", action=action, replacement=replacement)
