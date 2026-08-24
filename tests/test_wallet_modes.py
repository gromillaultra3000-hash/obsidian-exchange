#!/usr/bin/env python3
"""Разделение non-KYC обмена и внешних KYC-бирж в кошельке."""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "relay"))

from core.wallet_modes import public_modes  # noqa: E402

data = public_modes()
modes = {row["id"]: row for row in data["modes"]}

assert data["default"] == "private_exchange"
assert modes["private_exchange"]["status"] == "available"
assert modes["private_exchange"]["badge"] == "Без KYC"
assert modes["verified_exchanges"]["status"] == "planned"
assert "сама биржа" in modes["verified_exchanges"]["identity"]
assert "раздельно" in data["portfolioRule"]

first = public_modes()
first["modes"][0]["title"] = "changed"
assert public_modes()["modes"][0]["title"] == "Приватный обмен"

print("OK: wallet service modes are explicit and isolated")
