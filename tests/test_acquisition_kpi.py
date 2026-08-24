import sqlite3

from relay.services.acquisition_kpi import FORBIDDEN_KEYS, build_acquisition_kpi_report


def _database():
    connection = sqlite3.connect(":memory:")
    connection.executescript(
        "CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,currency TEXT,rub_amount REAL,status TEXT,created_at TEXT);"
        "CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,provider TEXT);"
    )
    order_id = 1
    for month, users in [("2026-01", 12), ("2026-02", 5)]:
        for user in range(1, users + 1):
            user_id = user if month == "2026-01" else 100 + user
            connection.execute(
                "INSERT INTO orders VALUES(?,?,?,?,?,?)",
                (order_id, user_id, "BTC", 1000, "sent", f"{month}-05 12:00:00"),
            )
            connection.execute("INSERT INTO payment_sessions VALUES(?,?,?)", (order_id, order_id, "provider-a"))
            order_id += 1
            if month == "2026-01" and user <= 3:
                connection.execute(
                    "INSERT INTO orders VALUES(?,?,?,?,?,?)",
                    (order_id, user_id, "BTC", 500, "sent", "2026-01-06 12:00:00"),
                )
                connection.execute("INSERT INTO payment_sessions VALUES(?,?,?)", (order_id, order_id, "provider-a"))
                order_id += 1
    connection.execute(
        "INSERT INTO orders VALUES(?,?,?,?,?,?)",
        (order_id, 999, "ETH", 2000, "expired", "2026-01-07 12:00:00"),
    )
    connection.commit()
    return connection


def _walk_keys(value):
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def test_report_is_aggregate_privacy_safe_and_small_cohorts_are_suppressed():
    with _database() as connection:
        report = build_acquisition_kpi_report(connection, as_of="2026-03-01T00:00:00Z")
    assert not (set(_walk_keys(report)) & FORBIDDEN_KEYS)
    assert [row["month"] for row in report["monthly_performance"]["rows"]] == ["2026-01"]
    assert report["monthly_performance"]["suppressed_month_count"] == 1
    assert [row["cohort_month"] for row in report["acquisition_cohorts"]["rows"]] == ["2026-01"]
    assert report["acquisition_cohorts"]["suppressed_cohort_count"] == 1


def test_fulfilled_gmv_is_sent_only_and_never_claimed_as_revenue():
    with _database() as connection:
        report = build_acquisition_kpi_report(connection, as_of="2026-03-01T00:00:00Z")
    assert report["order_funnel"]["fulfilled_orders"] == 20
    assert report["order_funnel"]["fulfilled_gmv_rub"] == 18500.0
    assert report["evidence_limitations"]["revenue_available"] is False
    assert report["evidence_limitations"]["fulfilled_volume_is_gmv_not_revenue"] is True


def test_repeat_rate_uses_fulfilled_orders_only():
    with _database() as connection:
        report = build_acquisition_kpi_report(connection, as_of="2026-03-01T00:00:00Z")
    assert report["user_quality"]["fulfilled_users"] == 17
    assert report["user_quality"]["repeat_fulfilled_users"] == 3
    assert report["user_quality"]["repeat_rate_among_fulfilled_users"] == round(3 / 17, 6)


def test_report_hash_is_deterministic_and_binds_content():
    with _database() as connection:
        first = build_acquisition_kpi_report(connection, as_of="2026-03-01T00:00:00Z")
        second = build_acquisition_kpi_report(connection, as_of="2026-03-01T00:00:00Z")
    assert first["report_sha256"] == second["report_sha256"]
    changed = dict(second)
    changed["as_of"] = "2026-03-02T00:00:00Z"
    with _database() as connection:
        third = build_acquisition_kpi_report(connection, as_of=changed["as_of"])
    assert third["report_sha256"] != first["report_sha256"]


def test_minimum_cohort_threshold_cannot_be_weakened_below_ten():
    with _database() as connection:
        try:
            build_acquisition_kpi_report(connection, as_of="2026-03-01T00:00:00Z", minimum_cohort_users=9)
        except ValueError as exc:
            assert str(exc) == "minimum_cohort_users_must_be_at_least_10"
        else:
            raise AssertionError("accepted unsafe cohort threshold")


def test_provider_and_currency_mix_apply_threshold():
    with _database() as connection:
        report = build_acquisition_kpi_report(connection, as_of="2026-03-01T00:00:00Z")
    assert report["currency_mix"] == [{"currency": "BTC", "fulfilled_orders": 20, "fulfilled_gmv_rub": 18500.0}]
    assert report["payment_session_provider_mix"] == [{"provider": "provider-a", "recorded_fulfilled_orders": 20}]
