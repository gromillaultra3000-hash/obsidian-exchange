import ast
from pathlib import Path

BOT_PATH = Path(__file__).resolve().parents[1] / "bot" / "main_bot.py"
TEXT = BOT_PATH.read_text("utf-8")
TREE = ast.parse(TEXT)


def function(name):
    return next(n for n in TREE.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                and n.name == name)


def test_bot_has_no_bitcoinlib_or_secure_wallet_send_path():
    assert "bitcoinlib.wallets" not in TEXT
    assert "def send_crypto(" not in TEXT
    assert "def _unlock_payout_wallets(" not in TEXT
    assert "_unlock_payout_wallets()" not in TEXT
    assert "WALLET_PAYOUT_PASSWORD" not in TEXT


def test_order_payout_only_creates_intent():
    src = ast.get_source_segment(TEXT, function("process_payout"))
    assert "_payout_store.create_order(" in src
    assert "db_conn(" not in src
    assert "_pi.claim(" not in src
    assert "_pi.succeed(" not in src
    assert "_pi.review(" not in src
    assert "preview_send" not in src and ".send(" not in src


def test_order_intent_admin_paths_use_repository_and_keep_evidence_guards():
    review_src = ast.get_source_segment(TEXT, function("cmd_payout_intent_review"))
    confirm_src = ast.get_source_segment(TEXT, function("cmd_payout_confirm"))
    requeue_src = ast.get_source_segment(TEXT, function("cmd_payout_requeue"))
    usdt_src = ast.get_source_segment(TEXT, function("auto_check_usdt"))

    assert "_payout_store.review_items(" in review_src
    assert "FROM payout_intents" not in review_src
    assert "_payout_store.order(" in confirm_src
    assert "_payout_store.confirm_order_txid(" in confirm_src
    assert "candidates_for" in confirm_src and "chain_final" in confirm_src
    assert "_payout_store.order(" in requeue_src
    assert "inspect_attempt" in requeue_src
    assert 'proof.get("verdict") != "absent"' in requeue_src
    assert "_payout_store.requeue_order_absent(" in requeue_src
    assert "_payout_store.order_exists(" in usdt_src


def test_referral_withdrawal_does_not_sign_or_zero_balance():
    src = ast.get_source_segment(TEXT, function("withdraw_referral_bonus"))
    assert "send_crypto" not in src
    assert "total_bonus_btc=0" not in src
    assert "_payout_store.request_referral(" in src
    assert "_user_profiles.referral_address(" in src
    assert "db_conn(" not in src and "_rpi." not in src


def test_referral_admin_paths_use_repository_and_keep_evidence_guards():
    review_src = ast.get_source_segment(TEXT, function("cmd_payout_intent_review"))
    confirm_src = ast.get_source_segment(TEXT, function("cmd_refpayout_confirm"))
    requeue_src = ast.get_source_segment(TEXT, function("cmd_refpayout_requeue"))

    assert "_payout_store.referral_review_items(" in review_src
    assert "FROM referral_payout_intents" not in review_src
    assert "_payout_store.referral(" in confirm_src
    assert "candidates_for_debt" in confirm_src
    assert 'and c.get("trusted")' in confirm_src
    assert "chain_final trusted" in confirm_src
    assert "_payout_store.confirm_referral_txid(" in confirm_src
    assert "_payout_store.referral(" in requeue_src
    assert "inspect_attempt" in requeue_src
    assert 'proof.get("verdict") != "absent"' in requeue_src
    assert "_payout_store.requeue_referral_absent(" in requeue_src
    assert "db_conn(" not in confirm_src and "db_conn(" not in requeue_src
    assert "referral_payout_intents" not in TEXT and "_rpi" not in TEXT


if __name__ == "__main__":
    test_bot_has_no_bitcoinlib_or_secure_wallet_send_path()
    test_order_payout_only_creates_intent()
    test_order_intent_admin_paths_use_repository_and_keep_evidence_guards()
    test_referral_withdrawal_does_not_sign_or_zero_balance()
    test_referral_admin_paths_use_repository_and_keep_evidence_guards()
    print("bot signer isolation tests: OK")
