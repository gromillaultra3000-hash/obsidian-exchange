"""Execute the actual payment script against a deterministic clock and timers."""
import datetime
import json
import os
from pathlib import Path
import subprocess

import pytest

ROOT = Path(__file__).resolve().parents[1]


def run(value, **options):
    tz = options.pop('tz', 'UTC')
    result = subprocess.run(['node', str(ROOT / 'tests/e4_payment_expiry_behavior.cjs')],
        input=json.dumps({'path': str(ROOT / 'relay-fastapi/main.py'), 'value': value, **options}),
        capture_output=True, text=True, check=True, env={**os.environ, 'TZ': tz})
    return json.loads(result.stdout)


@pytest.mark.parametrize('tz', ['UTC', 'America/New_York', 'Asia/Kolkata'])
@pytest.mark.parametrize('value', [
    '2026-09-08T12:15:00Z', '2026-09-08T12:15:00+00:00',
    '2026-09-08T15:15:00+03:00', '2026-09-08T06:45:00-05:30',
    '2026-09-08T17:45:00+05:30', '2026-09-08 12:15:00',
    '2026-09-08T12:15:00', '2026-09-08 15:15:00+03:00',
])
def test_same_instant_independent_of_browser_timezone(value, tz):
    result = run(value, tz=tz, repeat=True)
    assert '<b>15:00</b>' in result['timer']
    assert result['state']['status'] == 'pending' and not result['localExpired']
    assert result['intervals'] == 1


@pytest.mark.parametrize('value', [
    '2024-02-29T12:15:00.123456+03:00', '0099-01-01T00:00:00Z',
    '0001-01-01T00:00:00Z', '9999-12-31T23:59:59.999999Z',
    '2026-09-08T12:15:00.1Z', '2026-09-08T12:15:00.123456-05:30',
])
def test_supported_dates_match_python_datetime_instant(value):
    # Float timestamp rounding at year 9999 is not a precision oracle.
    dt = datetime.datetime.fromisoformat(value).astimezone(datetime.timezone.utc)
    delta = dt - datetime.datetime(1970, 1, 1, tzinfo=datetime.timezone.utc)
    expected = delta.days * 86400000 + delta.seconds * 1000 + delta.microseconds // 1000
    assert run(value, mode='parse')['milliseconds'] == expected


@pytest.mark.parametrize('value', [None, '', False, True, 0, 1788869700000, {}, [],
    'not-a-date', '2026-02-30T12:00:00Z', '2025-02-29T12:00:00Z',
    '2026-04-31T12:00:00Z', '2026-09-08T24:00:00Z',
    '2026-09-08T12:60:00Z', '2026-09-08T12:00:60Z',
    '0000-01-01T00:00:00Z', '2026-00-08T12:00:00Z',
    '2026-09-00T12:00:00Z', '2026-09-08',
    '2026-09-08T12:00:00+24:00', '2026-09-08T12:00:00+00:60',
    '2026-09-08T12:00:00+00:00Z', '2026-09-08T12:00:00.1234567Z',
    '2026-09-08T12:00:00Z\n', '<img src=x onerror=alert(1)>', 'x' * 1000])
def test_invalid_metadata_has_unknown_time_without_invented_expiry(value):
    result = run(value, poll=True)
    assert result['timer'] == 'Срок действия реквизитов уточняется.'
    assert result['state']['status'] == 'pending' and not result['localExpired']
    assert result['intervals'] == 0 and len(result['requests']) == 1
    assert 'class="reqs"' in result['html']
    assert 'NaN' not in result['timer'] and '<img' not in result['timer']


@pytest.mark.parametrize('value,advance', [('2026-09-08T11:59:59Z', 0),
    ('2026-09-08T12:00:00Z', 0), ('2026-09-08T12:00:01Z', 1000)])
def test_local_expiry_stops_countdown_but_poll_can_receive_paid(value, advance):
    result = run(value, advance=advance, poll=True, pollState={'status': 'paid'})
    assert result['localExpired'] and result['intervals'] == 0
    assert result['state']['status'] == 'paid' and len(result['requests']) == 1
    assert 'Оплата получена' in result['html']


@pytest.mark.parametrize('state,text', [
    ({'status': 'failed'}, 'Заявка не выполнена'),
    ({'status': 'cancelled'}, 'Заявка отменена'),
    ({'status': 'expired'}, 'Срок оплаты заявки истёк'),
    ({'status': 'paid'}, 'Оплата получена'),
    ({'status': 'sent'}, 'Выполнено'),
    ({'receipt': 'sent'}, 'Чек получен'),
    ({'verification': 'pdf', 'receipt': 'stored'}, 'Требуется подтверждение'),
    ({'dead': True, 'receipt': 'stored'}, 'Файл чека получен'),
])
def test_timer_cannot_override_existing_outcome_or_receipt_view(state, text):
    result = run('2026-09-08T11:59:59Z', state=state)
    assert text in result['html'] and result['intervals'] == 0
    assert not result['localExpired']
