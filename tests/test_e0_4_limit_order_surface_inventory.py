import json
import hashlib
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_limit_orders_have_exact_six_surface_inventory_and_runtime_limits():
    matrix=json.loads((ROOT/"docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    item=next(feature for feature in matrix["features"] if feature["id"]=="LIMIT_ORDERS")
    assert set(item["cells"])==set(matrix["surfaces"])
    assert item["moneyWriter"] is True and item["overallStatus"]=="PARTIAL_NOT_ACCEPTED"
    assert item["cells"]["telegramBot"]==dict(item["cells"]["telegramBot"], mode="REQUIRED", implementation="IMPLEMENTED")
    assert item["cells"]["admin"]["mode"]=="OPERATOR_ONLY"
    assert item["cells"]["admin"]["implementation"]=="PARTIAL"
    assert all(item["cells"][name]["mode"]=="N/A" for name in ("site","miniApp","api","native"))
    assert "limit orders" not in matrix["omittedFeatureFamilies"]
    assert "LUMI advisory" not in matrix["omittedFeatureFamilies"]
    evidence=json.loads((ROOT/"docs/e0-4-limit-order-runtime-observation.v1.json").read_text())
    assert evidence["productionMutation"] is False
    assert evidence["authenticatedCustomerAction"] is False
    assert evidence["telegramDelivery"] is False
    assert evidence["moneyWriterExercised"] is False
    assert evidence["telegramBot"]["configuredEnabled"] is True
    assert evidence["telegramBot"]["unit"]["name"]=="exchange-bot.service"
    assert evidence["telegramBot"]["configuredEnvironmentNameObserved"]=="LIMIT_ORDER_POSTGRES_ENABLED"
    assert evidence["telegramBot"]["sourceDrift"] is True
    checkout_hash=hashlib.sha256((ROOT/"bot/main_bot.py").read_bytes()).hexdigest()
    repository_hash=hashlib.sha256((ROOT/"relay/repositories/limit_order_store.py").read_bytes()).hexdigest()
    admin_hash=hashlib.sha256((ROOT/"admin-panel/app/Filament/Resources/LimitOrderResource.php").read_bytes()).hexdigest()
    assert evidence["telegramBot"]["checkoutMainSha256"]==checkout_hash
    assert evidence["telegramBot"]["deployedMainSha256"]!=checkout_hash
    assert evidence["repository"]["deployedAndCheckoutSha256"]==repository_hash
    assert evidence["admin"]["resourceSha256"]==admin_hash
    assert set(evidence["telegramBot"]["deployedAnchors"])=={"menu_limit","lo_confirm","lo_list","cancelimit","limit_order_watcher","asyncio.create_task(limit_order_watcher())"}
    assert evidence["database"]["totalRows"]==0
    assert evidence["database"]["limitAttributedOrderRows"]==0
    assert sum(evidence["database"][name] for name in ("activeRows","triggeredRows","expiredRows","cancelledRows"))==evidence["database"]["totalRows"]
    assert evidence["database"]["catalogSource"]=="information_schema.columns"
    assert evidence["database"]["createdAtPresent"] is False
    assert "created_at" not in evidence["database"]["observedColumns"]
    assert evidence["surfaceContractSource"]=="docs/e0-3-bot-b5-5-automation-gift-writers-rehearsal.v1.json#surfaceMatrix"
    assert set(evidence["negativeSurfaces"])=={"site","miniApp","api","native"}
    assert evidence["acceptance"]=="PARTIAL_NOT_ACCEPTED"

def test_limit_order_admin_and_fail_closed_gaps_remain_visible():
    schema=(ROOT/"deploy/postgres/006_scheduled_orders.sql").read_text()
    admin=(ROOT/"admin-panel/app/Filament/Resources/LimitOrderResource.php").read_text()
    bot=(ROOT/"bot/main_bot.py").read_text()
    store=(ROOT/"relay/repositories/limit_order_store.py").read_text()
    evidence=json.loads((ROOT/"docs/e0-4-limit-order-runtime-observation.v1.json").read_text())
    assert "created_at" not in schema and "created_at" in admin
    currencies=bot[bot.index("_LIMIT_CURRENCIES"):bot.index("@router.callback_query(F.data == \"menu_limit\")")]
    assert "'ETH' => 'ETH'" in admin and "ETH" not in currencies
    watcher=bot[bot.index("async def limit_order_watcher"):bot.index("# ---------- МОНИТОРИНГ САЙТА ----------")]
    post_trigger=watcher[watcher.index("result=store.trigger"):]
    assert post_trigger.index("result=store.trigger") < post_trigger.index("await bot.send_message") < post_trigger.index("except Exception:\n                    pass")
    confirm=bot[bot.index("async def lo_confirm"):bot.index("# (снят дубль /limits")]
    assert "is_user_blocked" not in confirm and "idempotency" not in confirm
    success=confirm[confirm.index("Управление:"):]
    assert "/limits" in success
    admin_limits=bot[bot.index("async def cmd_limits"):bot.index("async def check_stuck_orders")]
    assert "is_admin(message.from_user.id)" in admin_limits
    assert "SELECT id,user_id,currency,target_rate,direction,rub_amount,crypto_address AS destination,expires_at FROM limit_orders" in store
    assert any("hard-coded fallback" in finding for finding in evidence["riskFindings"])
    assert any("unbounded" in finding for finding in evidence["riskFindings"])
