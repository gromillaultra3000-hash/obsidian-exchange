"""Execute the shipped Mini App recipient/review JavaScript without network access.

These tests need Node, but no npm packages or browser download. Set
E4_WEBAPP_SOURCE to another webapp.html to demonstrate regressions against a
baseline. Address fixtures deliberately exercise shape, not chain checksums;
the server remains responsible for definitive destination validation.
"""

import json
import os
from pathlib import Path
import shutil
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[1]
RUNNER = Path(__file__).with_suffix(".cjs").with_name("e4_recipient_review_behavior.cjs")
WEBAPP = Path(os.environ.get("E4_WEBAPP_SOURCE", ROOT / "relay/webapp.html"))


def run_case(case, **parameters):
    node = shutil.which("node")
    assert node, "Node is required for executable Mini App review regression tests"
    result = subprocess.run(
        [node, str(RUNNER), str(WEBAPP), case, json.dumps(parameters)],
        cwd=ROOT,
        text=True,
        capture_output=True,
        timeout=15,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


@pytest.mark.parametrize("tag_mode", ["hidden", "tag", "no_tag", "missing_tag"])
def test_buy_review_shows_full_destination_and_captures_confirmed_fields(tag_mode):
    run_case("buy_snapshot", tag_mode=tag_mode)


@pytest.mark.parametrize("embedded", [False, True], ids=["separate-memo", "embedded-memo"])
def test_memo_preserves_repeated_spaces_and_escapes_markup(embedded):
    run_case("literal_memo", embedded=embedded)


@pytest.mark.parametrize("method", ["sbp", "card"])
def test_sell_review_matches_normalized_writer_payload_after_form_changes(method):
    run_case("sell_snapshot", method=method)


@pytest.mark.parametrize(
    ("currency", "network", "address"),
    [
        ("BTC", "MAINNET", "not-a-bitcoin-address"),
        ("LTC", "MAINNET", "ltc1bad"),
        ("ETH", "ERC20", "0x1234"),
        ("USDT", "ERC20", "T" + "1" * 33),
        ("USDT", "TRC20", "0x" + "a" * 40),
        ("XRP", "MAINNET", "broken:42"),
        ("TON", "MAINNET", "broken#memo"),
        ("XMR", "MAINNET", "4" + "0" * 94),
    ],
    ids=["btc", "ltc", "eth", "usdt-erc20", "usdt-trc20", "xrp", "ton", "xmr"],
)
def test_known_invalid_destination_never_opens_review_or_calls_writer(currency, network, address):
    run_case("invalid_destination", currency=currency, network=network, address=address)


@pytest.mark.parametrize(
    ("currency", "network", "address"),
    [
        ("XRP", "MAINNET", "r" + "p" * 25 + ":42"),
        ("XRP", "MAINNET", "X" + "p" * 46),
        ("TON", "MAINNET", "EQ" + "A" * 46 + "#invoice  42"),
        ("TON", "MAINNET", "0:" + "ab" * 32),
        ("TON", "MAINNET", "-1:" + "CD" * 32 + "#invoice-42"),
        ("BTC", "MAINNET", "BC1" + "Q" * 39),
        ("BTC", "MAINNET", "bc1" + "q" * 87),
        ("BTC", "MAINNET", "BC1" + "Q" * 87),
        ("LTC", "MAINNET", "LTC1" + "Q" * 39),
        ("LTC", "MAINNET", "ltc1" + "q" * 86),
        ("LTC", "MAINNET", "LTC1" + "Q" * 86),
        ("USDT", "ERC20", "0x" + "ab" * 20),
        ("USDT", "TRC20", "T" + "1" * 33),
    ],
    ids=["xrp-tag", "xrp-x-address", "ton-memo", "ton-raw", "ton-raw-memo",
         "btc-uppercase", "btc-long", "btc-long-uppercase", "ltc-uppercase",
         "ltc-long", "ltc-long-uppercase", "usdt-erc20", "usdt-trc20"],
)
def test_supported_destination_shapes_reach_review_unchanged(currency, network, address):
    run_case("accepted_destination", currency=currency, network=network, address=address)


def test_unknown_asset_defers_destination_validation_to_server():
    run_case("unknown_destination")


@pytest.mark.parametrize(
    "boundary",
    ["unacknowledged", "fresh-once", "exact-expiry", "timer-expiry", "cancel", "escape", "reopen"],
)
def test_real_review_event_handlers_enforce_acknowledgement_and_freshness(boundary):
    run_case("review_boundary", boundary=boundary)
