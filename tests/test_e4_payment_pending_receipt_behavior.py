"""Stored evidence remains visible beside unavailable instructions/verification."""
import pytest

from test_e4_payment_terminal_behavior import render


@pytest.mark.parametrize('verification', ['', 'video', 'pdf'])
@pytest.mark.parametrize('timer', [False, True])
def test_stored_unavailable_file_fact_keeps_verification_and_pending(verification, timer):
    result = render(status='pending', receipt='stored', dead=True,
                    verification=verification, localExpired=timer)
    html = result['html']
    assert 'Файл чека получен, но платёжному партнёру пока не передан.' in html
    assert html.count('pending-receipt-evidence') == 1
    assert all(x not in html for x in ['<button', 'class="reqs"', 'class="qr"',
        'Оплата получена', 'Заявкой занимается сотрудник', 'Обычно до', 'и передан платёжному'])
    assert 'не переводите' in html and 'Поддержка в Telegram' in html
    assert result['state']['status'] == 'pending' and result['state']['receipt'] == 'stored'
    if verification:
        assert 'Требуется подтверждение' in html
        assert ('видео' if verification == 'video' else 'PDF-чек') in html


@pytest.mark.parametrize('verification', ['', 'video', 'pdf'])
def test_delivered_receipt_is_not_downgraded_to_stored(verification):
    html = render(status='pending', receipt='sent', dead=True,
                  verification=verification)['html']
    assert 'Чек получен' in html
    assert 'пока не передан' not in html and '<button' not in html
    if verification:
        assert 'и передан платёжному партнёру' in html
        assert 'Требуется подтверждение' in html


@pytest.mark.parametrize('verification', ['', 'video', 'pdf'])
def test_absent_receipt_never_invents_file_evidence(verification):
    html = render(status='pending', receipt='', dead=True, verification=verification)['html']
    assert 'pending-receipt-evidence' not in html
    assert 'получен' not in html and '<button' not in html


@pytest.mark.parametrize('receipt', ['future-state', '<script>unsafe</script>', True])
@pytest.mark.parametrize('dead', [False, True])
def test_unknown_receipt_cannot_become_stored_evidence_on_expiry(receipt, dead):
    html = render(status='pending', receipt=receipt, dead=dead, localExpired=True)['html']
    assert 'Файл получен' not in html and 'чека получен' not in html
    assert 'pending-receipt-evidence' not in html and '<script>' not in html


def test_active_stored_session_keeps_existing_payment_presentation():
    html = render(status='pending', receipt='stored', dead=False, localExpired=False)['html']
    assert 'class="reqs"' in html and 'Ожидаем оплату' in html
    assert 'pending-receipt-evidence' not in html
