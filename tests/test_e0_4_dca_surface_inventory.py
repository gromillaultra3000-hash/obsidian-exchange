import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_dca_has_exact_six_surface_inventory_and_runtime_limits():
    matrix=json.loads((ROOT/"docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    dca=next(item for item in matrix["features"] if item["id"]=="DCA_SCHEDULES")
    assert set(dca["cells"])==set(matrix["surfaces"])
    assert dca["moneyWriter"] is True and dca["overallStatus"]=="PARTIAL_NOT_ACCEPTED"
    assert dca["cells"]["telegramBot"]["mode"]=="REQUIRED"
    assert dca["cells"]["admin"]["mode"]=="OPERATOR_ONLY"
    assert dca["cells"]["admin"]["implementation"]=="PARTIAL"
    assert all(dca["cells"][name]["mode"]=="N/A" for name in ("site","miniApp","api","native"))
    assert "DCA" not in matrix["omittedFeatureFamilies"]
    assert "LUMI advisory" not in matrix["omittedFeatureFamilies"]
    evidence=json.loads((ROOT/"docs/e0-4-dca-runtime-observation.v1.json").read_text())
    assert evidence["productionMutation"] is False
    assert evidence["authenticatedCustomerAction"] is False
    assert evidence["moneyWriterExercised"] is False
    assert evidence["database"]["scheduleRows"]==0
    assert evidence["telegramBot"]["configuredEnabled"] is True
    assert evidence["acceptance"]=="PARTIAL_NOT_ACCEPTED"

def test_dca_admin_schema_drift_and_money_writer_anchors_remain_visible():
    schema=(ROOT/"deploy/postgres/006_scheduled_orders.sql").read_text()
    admin=(ROOT/"admin-panel/app/Filament/Resources/DcaScheduleResource.php").read_text()
    bot=(ROOT/"bot/main_bot.py").read_text()
    assert "runs_limit" not in schema and "runs_limit" in admin
    assert "'paused'" not in schema and "'paused'" in admin
    assert "async def dca_runner" in bot and "run_due(" in bot
    assert "_rate or 0" in bot and "agreed_crypto_amount=float(_crypto or 0)" in bot
