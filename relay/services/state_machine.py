ALLOWED_TRANSITIONS = {
    'created': ['invoice_created', 'failed'],
    'invoice_created': ['awaiting_payment', 'expired'],
    'awaiting_payment': ['payment_detected', 'expired'],
    'payment_detected': ['confirming', 'failed'],
    'confirming': ['payout_queued', 'failed'],
    'payout_queued': ['payout_sent', 'failed'],
    'payout_sent': ['completed', 'failed'],
    'completed': [],
    'expired': [],
    'failed': ['invoice_created'],
}

class PaymentStateMachine:
    @staticmethod
    def transition(current_status, new_status):
        if new_status not in ALLOWED_TRANSITIONS.get(current_status, []):
            raise ValueError(f"Transition from '{current_status}' to '{new_status}' is not allowed")
        return new_status
