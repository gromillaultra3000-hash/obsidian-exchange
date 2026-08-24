from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_postgres_web_customer_orders_does_not_use_untyped_null_probe():
    source = (ROOT / "relay/repositories/order_read_store.py").read_text()
    postgres = source.split("class PostgresOrderReadStore", 1)[1]
    method = postgres.split("def web_customer_orders", 1)[1].split("def receipt_order_ids", 1)[0]

    assert "web_user_id=%s OR user_id=%s" in method
    assert "%s IS NOT NULL" not in method


def test_reserves_normalizes_postgres_decimal_before_rate_multiplication():
    source = (ROOT / "relay-fastapi/main.py").read_text()
    endpoint = source.split("async def api_reserves", 1)[1].split("async def webapp", 1)[0]

    assert "float(amt) * float(rate)" in endpoint
    assert "amt * rate" not in endpoint


def test_failed_provider_cancel_stops_current_drain_pass():
    source = (ROOT / "relay-fastapi/main.py").read_text()
    dispatcher = source.split("def _dispatch_lifecycle_work", 1)[1].split(
        "async def cleanup_expired_orders", 1
    )[0]
    failed_cancel = dispatcher.split("if not ok:", 1)[1].split(
        "logger.info", 1
    )[0]

    assert "retry_work(item[\"id\"])" in failed_cancel
    assert "break" in failed_cancel
    assert "continue" not in failed_cancel
