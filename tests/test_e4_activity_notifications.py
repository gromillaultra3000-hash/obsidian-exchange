from pathlib import Path


WEBAPP = (Path(__file__).resolve().parents[1] / "relay" / "webapp.html").read_text(encoding="utf-8")


def test_activity_unifies_telegram_notification_preferences_with_existing_bot_profile():
    assert 'id="activity-notifications"' in WEBAPP
    assert "Статусы заявок приходят в Telegram" in WEBAPP
    assert 'onclick="openBotProfile()"' in WEBAPP
    assert "function openBotProfile()" in WEBAPP
    assert "?start=profile" in WEBAPP


def test_activity_order_cards_expose_evidence_and_owner_controlled_support_handoff():
    history = WEBAPP[WEBAPP.index("function renderHistoryOrders"):
                     WEBAPP.index("function setHistoryFilter", WEBAPP.index("function renderHistoryOrders"))]
    assert 'history-evidence' in history
    assert "Чек передан на проверку. Не оплачивайте повторно." in history
    assert "Доказательство выдачи — ссылка на транзакцию выше." in history
    assert 'history-support-order' in history

    handoff = WEBAPP[WEBAPP.index("async function openOrderSupport"):
                     WEBAPP.index("function renderHistoryOrders", WEBAPP.index("async function openOrderSupport"))]
    assert "await copyOrderId(orderId)" in handoff
    assert "openSupport();" in handoff
    assert "в бот не передаём" in handoff
