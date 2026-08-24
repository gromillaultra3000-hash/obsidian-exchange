import hashlib
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_gifts_have_exact_six_surface_inventory_and_bounded_runtime_evidence():
    matrix=json.loads((ROOT/"docs/e0-4-feature-status-surface-matrix.v1.json").read_text())
    item=next(feature for feature in matrix["features"] if feature["id"]=="GIFT_VOUCHERS")
    assert list(item["cells"])==matrix["surfaces"]
    assert item["moneyWriter"] is True and item["overallStatus"]=="PARTIAL_NOT_ACCEPTED"
    assert item["cells"]["telegramBot"]["mode"]=="REQUIRED"
    assert item["cells"]["telegramBot"]["implementation"]=="PARTIAL"
    assert item["cells"]["admin"]["mode"]=="OPERATOR_ONLY"
    assert item["cells"]["admin"]["implementation"]=="PARTIAL"
    assert all(item["cells"][name]["mode"]=="N/A" for name in ("site","miniApp","api","native"))
    assert item["cells"]["site"]["implementation"]==item["cells"]["miniApp"]["implementation"]=="PARTIAL"
    assert "gifts" not in matrix["omittedFeatureFamilies"]
    assert "LUMI advisory" not in matrix["omittedFeatureFamilies"]
    evidence=json.loads((ROOT/"docs/e0-4-gift-runtime-observation.v1.json").read_text())
    for field in ("productionMutation","authenticatedCustomerAction","telegramDelivery","moneyWriterExercised","giftCodesReturnedByObservation"):
        assert evidence[field] is False
    assert evidence["acceptance"]=="PARTIAL_NOT_ACCEPTED"
    assert evidence["telegramBot"]["implementation"]=="PARTIAL"
    assert evidence["telegramBot"]["unit"]["name"]=="exchange-bot.service"
    assert evidence["telegramBot"]["configuredEnvironmentNameObserved"]=="GIFT_POSTGRES_ENABLED"
    assert evidence["telegramBot"]["configuredEnabled"] is True
    assert evidence["telegramBot"]["checkoutMainSha256"]==hashlib.sha256((ROOT/"bot/main_bot.py").read_bytes()).hexdigest()
    assert evidence["telegramBot"]["deployedMainSha256"]!=evidence["telegramBot"]["checkoutMainSha256"]
    assert evidence["repository"]["deployedAndCheckoutSha256"]==hashlib.sha256((ROOT/"relay/repositories/gift_store.py").read_bytes()).hexdigest()
    assert evidence["admin"]["resourceSha256"]==hashlib.sha256((ROOT/"admin-panel/app/Filament/Resources/GiftVoucherResource.php").read_bytes()).hexdigest()
    db=evidence["database"]
    assert sum(db[name] for name in ("pendingRows","paidRows","redeemedRows"))==db["totalRows"]==5
    assert db["giftIssueAttributedOrders"]==5 and db["giftRedeemAttributedOrders"]==0
    assert db["giftCodesReturnedByObservation"] is False and db["customerIdentifiersReturnedByObservation"] is False
    assert db["observedColumns"]==["id","sender_id","currency","rub_amount","code","status","order_id","recipient_id","recipient_address","created_at","claimed_at"]
    assert evidence["surfaceContractSource"]=="docs/e0-3-bot-b5-5-automation-gift-writers-rehearsal.v1.json#surfaceMatrix"
    assert set(evidence["negativeSurfaces"])=={"site","miniApp","api","native"}

def test_gift_redemption_delivery_bearer_and_admin_landmines_remain_visible():
    bot=(ROOT/"bot/main_bot.py").read_text()
    store=(ROOT/"relay/repositories/gift_store.py").read_text()
    schema=(ROOT/"deploy/postgres/005_gift_vouchers.sql").read_text()
    admin=(ROOT/"admin-panel/app/Filament/Resources/GiftVoucherResource.php").read_text()
    redeem=bot[bot.index("async def gift_enter_recipient_address"):bot.index("# ══════════════════════════════════════════════════════════════════\n# ГАРАНТИРОВАННЫЙ КУРС")]
    assert "store.redeem(" in redeem and "store=" not in redeem and "store =" not in redeem
    assert bot.count("_send_gift_card(")==1
    assert 'alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"' in bot and 'range(6)' in bot
    assert "WHERE code=%s" in store and "expires_at" not in schema
    assert "TextColumn::make('code')" in admin and "->searchable()" in admin and "->copyable()" in admin
    assert "CHECK(status IN('pending','paid','redeemed'))" in schema
    for drift in ("'claimed'", "'expired'", "'cancelled'", "'ETH' => 'ETH'"):
        assert drift in admin
    assert "redeemed_order_id" not in schema and "UNIQUE" not in schema.upper().split("ORDER_ID",1)[1]
    evidence=json.loads((ROOT/"docs/e0-4-gift-runtime-observation.v1.json").read_text())
    assert any("without defining store" in finding for finding in evidence["riskFindings"])
    assert any("roughly 30-bit" in finding for finding in evidence["riskFindings"])
    assert any("hard-coded fallback" in finding for finding in evidence["riskFindings"])
