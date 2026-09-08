"""Bounded payment-page reads using the installed order connection policy.

This adapter deliberately contains no provider calls or payment transitions.
Shared repositories may be older than Relay; do not replace their unrelated
customer, worker or writer behavior to provide these page-specific views.
"""
from repositories.order_read_store import (
    PostgresOrderReadStore, SQLiteOrderReadStore, _dict,
)


# Only pre-payment session states may offer payment instructions. A session's
# later state cannot confirm the order, but must not invite another transfer.
OPEN_SESSION_STATES = frozenset({
    'created', 'invoice_created', 'awaiting_payment',
})


def _authority(user_id, session_token):
    if user_id is not None:
        uid = int(user_id)
        if isinstance(user_id, bool) or uid <= 0:
            raise ValueError('invalid_payment_status_owner')
        # A verified subject always wins over a simultaneously supplied token.
        return uid, None
    token = str(session_token or '').strip()
    if not token or len(token) > 256:
        raise ValueError('invalid_payment_status_token')
    return None, token


class PaymentStatusReadStore:
    def __init__(self, order_store):
        if isinstance(order_store, PostgresOrderReadStore):
            self._marker = '%s'
        elif isinstance(order_store, SQLiteOrderReadStore):
            self._marker = '?'
        else:
            raise TypeError('unsupported_payment_status_store')
        self._store = order_store

    def _one(self, sql, params):
        # Only fixed SQL strings reach here; authority is always bound data.
        with self._store._c() as connection:
            row = connection.execute(sql.replace('?', self._marker), params).fetchone()
        return _dict(row) if row is not None else None

    @staticmethod
    def _scope(order_id, user_id, session_token):
        uid, token = _authority(user_id, session_token)
        oid = int(order_id)
        if oid <= 0:
            raise ValueError('invalid_payment_status_order')
        return oid, uid, token

    _OWNER = (
        '(o.user_id=? OR EXISTS(SELECT 1 FROM payment_sessions proof '
        'WHERE proof.order_id=o.order_id AND proof.session_token=?))'
    )

    def authorized_snapshot(self, order_id, *, user_id=None, session_token=None):
        return self._one(
            'SELECT o.order_id,o.rub_amount,o.status,o.paid_btc_tx,o.currency,'
            'o.network,o.verification_requested FROM orders o '
            'WHERE o.order_id=? AND ' + self._OWNER + ' LIMIT 1',
            self._scope(order_id, user_id, session_token))

    def get_by_token(self, token):
        value = str(token or '').strip()
        if not value or len(value) > 256:
            return None
        # An orphaned session cannot authorize a payment page.
        return self._one(
            'SELECT ps.amount,ps.order_id,ps.status,ps.provider_payload,'
            'ps.qr_payload,ps.expires_at FROM payment_sessions ps '
            'JOIN orders o ON o.order_id=ps.order_id '
            'WHERE ps.session_token=? LIMIT 1', (value,))

    def latest_for_authorized_order(self, order_id, *, user_id=None, session_token=None):
        return self._one(
            'SELECT ps.session_token,ps.status FROM orders o '
            'JOIN payment_sessions ps ON ps.order_id=o.order_id '
            'WHERE o.order_id=? AND ' + self._OWNER +
            ' ORDER BY ps.id DESC LIMIT 1',
            self._scope(order_id, user_id, session_token))

    def latest_active_for_authorized_order(self, order_id, *, user_id=None,
                                           session_token=None):
        row = self.latest_for_authorized_order(
            order_id, user_id=user_id, session_token=session_token)
        if (row and row['status'] in OPEN_SESSION_STATES
                and 0 < len(str(row['session_token'] or '').strip()) <= 256):
            return {'session_token': row['session_token']}
        return None

    def session_closed(self, order_id, *, user_id=None, session_token=None):
        uid, token = _authority(user_id, session_token)
        row = self.latest_for_authorized_order(
            order_id, user_id=uid, session_token=token)
        # Stale bearer links must not display their former payment instructions
        # just because a newer session for the same order is open.
        return (not row or row['status'] not in OPEN_SESSION_STATES
                or not (0 < len(str(row['session_token'] or '').strip()) <= 256)
                or (token is not None and row['session_token'] != token))

    def authorized_state(self, order_id, *, user_id=None, session_token=None):
        row = self._one(
            'SELECT o.receipt_sent_at FROM order_receipts r '
            'JOIN orders o ON o.order_id=r.order_id '
            'WHERE o.order_id=? AND ' + self._OWNER + ' LIMIT 1',
            self._scope(order_id, user_id, session_token))
        if row is None:
            return ''
        return 'sent' if str(row['receipt_sent_at'] or '').strip() else 'stored'
