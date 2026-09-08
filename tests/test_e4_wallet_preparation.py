"""Deterministic deferred preparation races; no network or real wallet signing."""
import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_name("e4_wallet_preparation.cjs")
WEBAPP = Path(os.environ.get("E4_WEBAPP_SOURCE", ROOT / "relay/webapp.html"))


def run_case(scenario, **parameters):
    node = shutil.which("node")
    assert node, "Node is required for production JavaScript preparation tests"
    result = subprocess.run(
        [node, str(RUNNER), str(WEBAPP), scenario, json.dumps(parameters)],
        cwd=ROOT, text=True, capture_output=True, timeout=15, check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("boundary", ["cancel", "close"])
@pytest.mark.parametrize("stage", ["fetch", "json"])
def test_cancelled_pending_preparation_cannot_reopen_review(action, boundary, stage):
    run_case("cancelled", action=action, boundary=boundary, stage=stage)


@pytest.mark.parametrize("action,replacement", [
    ("transfer", "transfer"), ("payment", "payment"),
    ("transfer", "payment"), ("payment", "transfer"),
])
@pytest.mark.parametrize("order", ["old-first", "old-last"])
@pytest.mark.parametrize("outcome", ["success", "fetch-reject", "json-reject", "http-error", "api-error"])
def test_latest_wallet_preparation_owns_review_and_status(action, replacement, order, outcome):
    run_case("superseded", action=action, replacement=replacement, order=order,
             outcome=outcome, stage="fetch")


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("order", ["old-first", "old-last"])
@pytest.mark.parametrize("outcome", ["success", "json-reject"])
def test_supersession_while_json_is_pending(action, order, outcome):
    run_case("superseded", action=action, replacement=action, order=order,
             outcome=outcome, stage="json")


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("replacement", ["buy", "sell"])
@pytest.mark.parametrize("boundary", ["open", "cancel", "escape", "expiry"])
def test_exchange_review_supersedes_pending_wallet_preparation(action, replacement, boundary):
    run_case("exchange_supersedes", action=action, replacement=replacement, boundary=boundary)


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("boundary", ["confirm", "cancel", "escape", "expiry"])
def test_current_response_requires_acknowledgement_and_hands_off_once(action, boundary):
    run_case("fresh", action=action, boundary=boundary)


@pytest.mark.parametrize("action", ["transfer", "payment"])
@pytest.mark.parametrize("replacement", ["transfer", "payment"])
def test_new_preparation_revokes_prior_acknowledged_handoff(action, replacement):
    run_case("preparing_replaces_review", action=action, replacement=replacement)
