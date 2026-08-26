from pathlib import Path


WEBAPP = Path(__file__).resolve().parents[1] / "relay" / "webapp.html"


def test_exchange_actions_open_a_clear_review_before_the_write_request():
    webapp = WEBAPP.read_text(encoding="utf-8")

    assert 'id="exchange-review"' in webapp
    assert 'role="dialog"' in webapp
    assert "function openExchangeReview" in webapp
    assert "function beginBuyOrder" in webapp
    assert "function createSellOrder" in webapp
    assert "onConfirm: () => submitBuyOrder" in webapp
    assert "onConfirm: () => submitSellOrder" in webapp
    assert "Я проверил(а) маршрут, сумму, сеть и реквизиты" in webapp
    assert "localStorage.setItem('lastAddress_' + currency + '_' + network, address)" in webapp


def test_review_explains_route_custody_fees_and_irreversibility_for_both_lanes():
    webapp = WEBAPP.read_text(encoding="utf-8")

    assert webapp.count("Маршрут и исполнитель") == 2
    assert webapp.count("{label: 'Custody'") == 2
    assert "Комиссия и расчёт" in webapp
    assert "Комиссия и курс" in webapp
    assert "необратим" in webapp
    assert "confirm.disabled = !ack.checked" in webapp
