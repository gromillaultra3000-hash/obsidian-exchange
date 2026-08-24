"""Fail-closed reconciliation of normalized financial components."""

from __future__ import annotations

import hashlib
import json
import re
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Iterable


SCHEMA = "obsidian-financial-component-report.v1"
COMPONENT_TYPES = {
    "customer_consideration", "crypto_acquisition_cost", "payment_provider_fee",
    "network_fee", "refund", "chargeback",
}
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
CENT = Decimal("0.01")


def _money(value: Any, *, positive: bool = False) -> Decimal:
    try:
        amount = Decimal(str(value)).quantize(CENT, rounding=ROUND_HALF_UP)
    except (InvalidOperation, ValueError):
        raise ValueError("financial_component_invalid_amount") from None
    if amount < 0 or (positive and amount <= 0) or amount != Decimal(str(value)):
        raise ValueError("financial_component_invalid_amount")
    return amount


def _timestamp_month(value: Any) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise ValueError("financial_component_invalid_timestamp")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError:
        raise ValueError("financial_component_invalid_timestamp") from None
    if parsed.utcoffset() is None:
        raise ValueError("financial_component_invalid_timestamp")
    return parsed.strftime("%Y-%m")


def _digest(report: dict[str, Any]) -> str:
    payload = {key: value for key, value in report.items() if key != "report_sha256"}
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def build_financial_component_report(
    fulfilled_orders: Iterable[dict[str, Any]],
    entries: Iterable[dict[str, Any]],
    *,
    as_of: str,
) -> dict[str, Any]:
    """Validate source-bound components and emit aggregates without row-level data."""
    _timestamp_month(as_of)
    orders: dict[int, Decimal] = {}
    for row in fulfilled_orders:
        if set(row) != {"order_id", "rub_amount", "status"} or row["status"] != "sent":
            raise ValueError("financial_component_invalid_fulfilled_order")
        order_id = int(row["order_id"])
        if order_id in orders:
            raise ValueError("financial_component_duplicate_order")
        orders[order_id] = _money(row["rub_amount"], positive=True)

    by_order: dict[int, list[tuple[str, Decimal, str]]] = defaultdict(list)
    entry_ids: set[str] = set()
    required = {"entry_id", "order_id", "recognized_at", "component_type", "amount_rub", "source_system", "source_record_sha256"}
    for entry in entries:
        if set(entry) != required:
            raise ValueError("financial_component_entry_shape")
        entry_id = entry["entry_id"]
        if not isinstance(entry_id, str) or not entry_id or entry_id in entry_ids:
            raise ValueError("financial_component_duplicate_or_invalid_entry_id")
        entry_ids.add(entry_id)
        order_id = int(entry["order_id"])
        if order_id not in orders:
            raise ValueError("financial_component_unknown_or_unfulfilled_order")
        component = entry["component_type"]
        if component not in COMPONENT_TYPES:
            raise ValueError("financial_component_unknown_type")
        if not isinstance(entry["source_system"], str) or not entry["source_system"].strip():
            raise ValueError("financial_component_source_required")
        if not isinstance(entry["source_record_sha256"], str) or not SHA256_RE.fullmatch(entry["source_record_sha256"]):
            raise ValueError("financial_component_invalid_source_digest")
        amount = _money(entry["amount_rub"], positive=component in {"customer_consideration", "crypto_acquisition_cost"})
        by_order[order_id].append((component, amount, _timestamp_month(entry["recognized_at"])))

    monthly: dict[str, dict[str, Decimal | int]] = defaultdict(lambda: {
        "complete_orders": 0, "customer_consideration_rub": Decimal(0),
        "crypto_acquisition_cost_rub": Decimal(0), "direct_fees_rub": Decimal(0),
        "refunds_and_chargebacks_rub": Decimal(0), "gross_economic_spread_rub": Decimal(0),
    })
    incomplete = 0
    for order_id, rub_amount in orders.items():
        components = by_order.get(order_id, [])
        consideration = [item for item in components if item[0] == "customer_consideration"]
        acquisition = [item for item in components if item[0] == "crypto_acquisition_cost"]
        provider_fees = [item for item in components if item[0] == "payment_provider_fee"]
        network_fees = [item for item in components if item[0] == "network_fee"]
        if (len(consideration) != 1 or len(acquisition) != 1 or len(provider_fees) != 1
                or len(network_fees) != 1 or consideration[0][1] != rub_amount):
            incomplete += 1
            continue
        month = consideration[0][2]
        if any(item[2] != month for item in components):
            raise ValueError("financial_component_cross_month_order")
        fees = sum((amount for kind, amount, _ in components if kind in {"payment_provider_fee", "network_fee"}), Decimal(0))
        losses = sum((amount for kind, amount, _ in components if kind in {"refund", "chargeback"}), Decimal(0))
        bucket = monthly[month]
        bucket["complete_orders"] += 1
        bucket["customer_consideration_rub"] += consideration[0][1]
        bucket["crypto_acquisition_cost_rub"] += acquisition[0][1]
        bucket["direct_fees_rub"] += fees
        bucket["refunds_and_chargebacks_rub"] += losses
        bucket["gross_economic_spread_rub"] += consideration[0][1] - acquisition[0][1] - fees - losses

    rows = []
    for month in sorted(monthly):
        row = {"month": month}
        row.update({key: (value if isinstance(value, int) else float(value)) for key, value in monthly[month].items()})
        rows.append(row)
    complete = len(orders) - incomplete
    report = {
        "schema": SCHEMA, "as_of": as_of,
        "coverage": {"fulfilled_orders": len(orders), "complete_orders": complete, "incomplete_orders": incomplete,
                     "complete_order_rate": round(complete / len(orders), 6) if orders else None},
        "monthly_economics": rows,
        "publication_gates": {
            "component_reconciliation_complete": bool(orders) and incomplete == 0,
            "gross_vs_net_policy_approved": False,
            "revenue_available": False, "gross_margin_available": False,
            "gross_economic_spread_is_not_revenue": True,
        },
        "report_sha256": "",
    }
    report["report_sha256"] = _digest(report)
    return report
