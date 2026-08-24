import pytest

from relay.services.financial_components import build_financial_component_report


DIGEST = "a" * 64


def _entry(entry_id, order_id, kind, amount, month="2026-07"):
    return {"entry_id": entry_id, "order_id": order_id, "recognized_at": f"{month}-10T12:00:00Z",
            "component_type": kind, "amount_rub": amount, "source_system": "reconciled-export",
            "source_record_sha256": DIGEST}


def test_complete_components_produce_economic_spread_but_never_revenue():
    orders = [{"order_id": 1, "rub_amount": "1000.00", "status": "sent"}]
    entries = [_entry("a", 1, "customer_consideration", "1000.00"),
               _entry("b", 1, "crypto_acquisition_cost", "920.00"),
               _entry("c", 1, "payment_provider_fee", "20.00"),
               _entry("d", 1, "network_fee", "5.00")]
    report = build_financial_component_report(orders, entries, as_of="2026-08-15T00:00:00Z")
    assert report["coverage"] == {"fulfilled_orders": 1, "complete_orders": 1, "incomplete_orders": 0, "complete_order_rate": 1.0}
    assert report["monthly_economics"][0]["gross_economic_spread_rub"] == 55.0
    assert report["publication_gates"]["revenue_available"] is False
    assert report["publication_gates"]["gross_margin_available"] is False


def test_missing_acquisition_cost_is_visible_and_excluded_not_guessed():
    orders = [{"order_id": 1, "rub_amount": "1000.00", "status": "sent"}]
    report = build_financial_component_report(orders, [_entry("a", 1, "customer_consideration", "1000.00")], as_of="2026-08-15T00:00:00Z")
    assert report["coverage"]["incomplete_orders"] == 1
    assert report["monthly_economics"] == []
    assert report["publication_gates"]["component_reconciliation_complete"] is False


def test_zero_fees_must_be_explicitly_evidenced():
    orders = [{"order_id": 1, "rub_amount": "1000.00", "status": "sent"}]
    base = [_entry("a", 1, "customer_consideration", "1000.00"),
            _entry("b", 1, "crypto_acquisition_cost", "900.00")]
    incomplete = build_financial_component_report(orders, base, as_of="2026-08-15T00:00:00Z")
    complete = build_financial_component_report(
        orders, base + [_entry("c", 1, "payment_provider_fee", "0.00"),
                        _entry("d", 1, "network_fee", "0.00")],
        as_of="2026-08-15T00:00:00Z")
    assert incomplete["coverage"]["incomplete_orders"] == 1
    assert complete["coverage"]["complete_orders"] == 1


@pytest.mark.parametrize("mutation,error", [
    ({"component_type": "profit"}, "financial_component_unknown_type"),
    ({"source_record_sha256": "not-a-digest"}, "financial_component_invalid_source_digest"),
    ({"amount_rub": -1}, "financial_component_invalid_amount"),
])
def test_invalid_or_unsupported_source_components_fail_closed(mutation, error):
    orders = [{"order_id": 1, "rub_amount": "1000.00", "status": "sent"}]
    entry = _entry("a", 1, "customer_consideration", "1000.00") | mutation
    with pytest.raises(ValueError, match=error):
        build_financial_component_report(orders, [entry], as_of="2026-08-15T00:00:00Z")


def test_consideration_must_match_order_and_report_digest_binds_content():
    orders = [{"order_id": 1, "rub_amount": "1000.00", "status": "sent"}]
    entries = [_entry("a", 1, "customer_consideration", "999.00"), _entry("b", 1, "crypto_acquisition_cost", "900.00")]
    first = build_financial_component_report(orders, entries, as_of="2026-08-15T00:00:00Z")
    second = build_financial_component_report(orders, entries, as_of="2026-08-16T00:00:00Z")
    assert first["coverage"]["incomplete_orders"] == 1
    assert first["report_sha256"] != second["report_sha256"]
