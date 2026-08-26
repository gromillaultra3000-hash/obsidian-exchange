from pathlib import Path


WEBAPP = Path(__file__).resolve().parents[1] / "relay" / "webapp.html"


def test_exchange_actions_open_a_clear_review_before_the_write_request():
    webapp = WEBAPP.read_text(encoding="utf-8")

    assert 'id="exchange-review"' in webapp
    assert 'role="dialog"' in webapp
    assert 'aria-describedby="exchange-review-description"' in webapp
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
    assert webapp.count("{label: 'Custody'") >= 2
    assert "Комиссия и расчёт" in webapp
    assert "Комиссия и курс" in webapp
    assert "необратим" in webapp
    assert "confirm.disabled = !ack.checked" in webapp
    assert "exchangeReviewRestoreFocus" in webapp
    assert "exchangeReviewFocusable" in webapp
    assert "event.key !== 'Tab'" in webapp
    assert "event.key === 'Escape'" in webapp
    assert "last.focus()" in webapp and "first.focus()" in webapp


def test_wallet_send_uses_the_same_explicit_review_before_wallet_signature():
    webapp = WEBAPP.read_text(encoding="utf-8")

    transfer = webapp[webapp.index("async function walletTransfer"):
                      webapp.index("function showSellCard", webapp.index("async function walletTransfer"))]
    assert "title: 'Отправить ' + d.amount + ' TON'" in transfer
    assert "Ваш подключённый TON-кошелёк" in transfer
    assert "Ключи остаются только в вашем кошельке" in transfer
    assert "Получатель" in transfer and "Сумма и сеть" in transfer
    assert "openExchangeReview({" in transfer
    assert "await tcUI.sendTransaction(d.request);" in transfer
    assert transfer.index("openExchangeReview({") < transfer.index("await tcUI.sendTransaction(d.request);")


def test_wallet_payment_for_a_sell_order_uses_review_before_wallet_signature():
    webapp = WEBAPP.read_text(encoding="utf-8")

    payment = webapp[webapp.index("async function walletPay"):
                     webapp.index("async function loadDues", webapp.index("async function walletPay"))]
    assert "title: 'Оплатить заявку #' + d.sell_id + ' из кошелька'" in payment
    assert "Комментарий к переводу" in payment
    assert "Заявка будет считаться оплаченной только после подтверждения в сети" in payment
    assert "openExchangeReview({" in payment
    assert "await tcUI.sendTransaction(d.request);" in payment
    assert payment.index("openExchangeReview({") < payment.index("await tcUI.sendTransaction(d.request);")
