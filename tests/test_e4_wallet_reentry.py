"""Reentry guidance against exact production JS; synthetic boundaries, no real signing."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name("e4_wallet_reentry.cjs")
WEBAPP = Path(os.environ.get("E4_WEBAPP_SOURCE", ROOT / "relay/webapp.html"))


def run_case(scenario, **parameters):
    node = shutil.which("node")
    assert node, "Node required for reentry acceptance"
    result = subprocess.run([node, str(RUNNER), str(WEBAPP), scenario, json.dumps(parameters)],
                            cwd=ROOT, text=True, capture_output=True, timeout=15, check=False)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "REENTRY_CASE_COMPLETE" in result.stdout, "scenario exited with unresolved promise"


@pytest.mark.parametrize("action", ["transfer", "payment"])
def test_fresh_review_explains_uncertain_previous_handoff_before_ack(action):
    run_case("fresh", action=action)


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("outcome", ["reject", "sync"])
def test_generic_sdk_failure_does_not_claim_transfer_failed(action, outcome):
    run_case("failure", action=action, outcome=outcome)


@pytest.mark.parametrize("action", ["transfer", "payment"])
def test_success_preserves_exact_request_and_signed_marker(action):
    run_case("success", action=action)
