"""Synthetic fixture and shared assertions for actual SQLite/PostgreSQL reads."""


def fixtures(connection, pg=False):
    mark = '%s' if pg else '?'
    connection.execute('CREATE TABLE orders(order_id INTEGER PRIMARY KEY,user_id INTEGER,'
                       'rub_amount NUMERIC,status TEXT,paid_btc_tx TEXT,currency TEXT,'
                       'network TEXT,verification_requested TEXT,receipt_sent_at TEXT)')
    connection.execute('CREATE TABLE payment_sessions(id INTEGER PRIMARY KEY,order_id INTEGER,'
                       'session_token TEXT UNIQUE,status TEXT,created_at TEXT,amount NUMERIC,'
                       'provider_payload TEXT,qr_payload TEXT,expires_at TEXT)')
    connection.execute('CREATE TABLE order_receipts(order_id INTEGER PRIMARY KEY)')
    # Explicit expectations independent of the implementation's allowlist.
    states = ['invoice_created', 'failed', 'expired', 'future-state', None, '',
              'created', 'awaiting_payment', 'payment_detected', 'confirming',
              'payout_queued', 'payout_sent', 'completed', 'paid']
    for oid, state in enumerate(states, 1):
        connection.execute('INSERT INTO orders VALUES('+','.join([mark]*9)+')',
                           (oid,7,2000,'pending','','TON','TON','',''))
        for ident, token, session_state, created in [
                (oid*10, f'old-{oid}', 'invoice_created', '2099-01-01'),
                (oid*10+1, f'latest-{oid}', state, '2000-01-01')]:
            connection.execute('INSERT INTO payment_sessions VALUES('+','.join([mark]*9)+')',
                               (ident,oid,token,session_state,created,2000,'{}','','2099-01-01'))
    connection.execute("INSERT INTO orders VALUES(99,8,4000,'pending','','TON','TON','','sent-marker')")
    connection.execute("INSERT INTO orders VALUES(100,7,4000,'pending','','TON','TON','','')")
    connection.execute("INSERT INTO payment_sessions VALUES(999,99,'foreign-token','invoice_created','2099-01-01',4000,'{}','','2099-01-01')")
    connection.execute("INSERT INTO payment_sessions VALUES(9999,9999,'orphan-token','invoice_created','2099-01-01',4000,'{}','','2099-01-01')")
    connection.execute('INSERT INTO order_receipts VALUES(1)')
    connection.execute('INSERT INTO order_receipts VALUES(99)')
    connection.commit()
    return states


def verify(reader, states):
    cases = 0
    for oid, state in enumerate(states, 1):
        expected_closed = oid not in {1, 7, 8}
        assert reader.authorized_snapshot(oid, user_id=7)['rub_amount'] == 2000
        assert reader.authorized_snapshot(oid, user_id=8) is None
        assert reader.authorized_snapshot(oid, session_token=f'latest-{oid}') is not None
        assert reader.authorized_snapshot(oid, user_id=8, session_token=f'latest-{oid}') is None
        assert reader.authorized_snapshot(oid, session_token='foreign-token') is None
        assert reader.session_closed(oid, user_id=7) is expected_closed
        assert reader.session_closed(oid, session_token=f'latest-{oid}') is expected_closed
        assert reader.session_closed(oid, session_token=f'old-{oid}') is True
        assert reader.latest_active_for_authorized_order(oid, user_id=7) == (
            None if expected_closed else {'session_token': f'latest-{oid}'})
        assert reader.latest_for_authorized_order(oid, user_id=8) is None
        assert reader.authorized_state(oid, user_id=8) == ''
        cases += 1
    assert reader.get_by_token('foreign-token')['order_id'] == 99
    assert reader.get_by_token('orphan-token') is None
    assert reader.get_by_token("' OR 1=1 --") is None
    assert reader.get_by_token('x'*257) is None
    assert reader.get_by_token('') is None
    assert reader.authorized_snapshot(100, user_id=7) is not None
    assert reader.session_closed(100, user_id=7) is True
    assert reader.authorized_state(1, user_id=7) == 'stored'
    assert reader.authorized_state(99, session_token='foreign-token') == 'sent'
    assert reader.authorized_state(99, user_id=7, session_token='foreign-token') == ''
    assert reader.authorized_state(100, user_id=7) == ''
    assert reader.authorized_snapshot(99, user_id=8, session_token='x'*257) is not None
    return cases + 12
