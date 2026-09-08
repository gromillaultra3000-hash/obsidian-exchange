"""Owner-scoped activity snapshot; order and latest session share one SELECT.

Keep this view separate from legacy bot/account order reads. The caller supplies
its existing repository connection policy; this module creates no new authority.
"""
from repositories.order_read_store import (
    PostgresOrderReadStore, SQLiteOrderReadStore, _dict,
)


SESSION_STATES = frozenset({
    'created', 'invoice_created', 'awaiting_payment', 'payment_detected',
    'confirming', 'payout_queued', 'payout_sent', 'completed', 'failed', 'expired',
})


def customer_orders(order_store, user_id: int, *, limit: int = 30):
    uid = int(user_id)
    if uid <= 0:
        raise ValueError('invalid_activity_owner')
    if isinstance(order_store, PostgresOrderReadStore):
        marker = '%s'
    elif isinstance(order_store, SQLiteOrderReadStore):
        marker = '?'
    else:
        raise TypeError('unsupported_activity_store')
    with order_store._c() as connection:
        rows = connection.execute(
            'SELECT o.order_id,o.rub_amount,o.crypto_address,o.currency,o.status,'
            'o.created_at,o.paid_btc_tx,o.network,o.receipt_sent_at,'
            'ps.session_token,ps.status AS payment_session_state '
            'FROM orders o LEFT JOIN payment_sessions ps '
            'ON ps.order_id=o.order_id AND ps.id=('
            'SELECT latest.id FROM payment_sessions latest WHERE latest.order_id=o.order_id '
            'ORDER BY latest.id DESC LIMIT 1) '
            f'WHERE o.user_id={marker} ORDER BY o.created_at DESC,o.order_id DESC LIMIT {marker}',
            (uid, min(100, max(1, int(limit)))),
        ).fetchall()
    result = []
    for row in rows:
        item = _dict(row)
        state = item['payment_session_state']
        item['payment_session_state'] = state if state in SESSION_STATES else 'unknown'
        # A failed/expired or unknown latest session must never revive an older
        # active token. Metadata is neither payment confirmation nor an order outcome.
        if item['payment_session_state'] in {'failed', 'expired', 'unknown'}:
            item['session_token'] = None
        result.append(item)
    return result
