import ast
import asyncio
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "relay"))
from repositories.bot_notification_store import PostgresB53HardenedBotNotificationStore, from_environment


class Result:
    def __init__(self, row): self.row = row
    def fetchone(self): return self.row


class Conn:
    def __init__(self, rows): self.rows, self.calls = iter(rows), []
    def __enter__(self): return self
    def __exit__(self, *_args): return False
    def execute(self, sql, args=None): self.calls.append((sql, args)); return Result(next(self.rows))


def test_hardened_store_uses_exact_principal_bound_functions():
    token, evidence = uuid.uuid4(), uuid.uuid4()
    bg = Conn([{"result": 1}] * 5)
    delivery = Conn([
        {"id": 1, "kind": "montera_admin", "dedupe_key": "1:9001", "payload": {"user_id": 101},
         "attempts": 1, "recipient_id": 9001, "attempt_token": token},
        {"result": "ALLOW"}, {"result": "SENT"}, {"result": "RETRY"}, {"result": True},
    ])
    transport = Conn([{"result": evidence}])
    store = object.__new__(PostgresB53HardenedBotNotificationStore)
    store.dsn, store.delivery_dsn, store.transport_dsn = "bg", "delivery", "transport"
    store._c = lambda: bg
    store._lane = lambda dsn, _lane: {"delivery": delivery, "transport": transport}[dsn]
    assert [
        store.queue_due_recalls(limit=1), store.queue_due_montera(limit=1),
        store.queue_due_abandoned(limit=1), store.queue_due_payout_delays(warn_minutes=999, limit=1),
        store.queue_due_winbacks(discount=99, valid_hours=999, limit=1),
    ] == [1] * 5
    item = store.claim_notification()
    assert item["recipient_id"] == 9001 and item["attempt_token"] == str(token)
    correlation = str(uuid.uuid4())
    assert store.pre_submit(1, attempt_token=str(token), client_correlation_id=correlation) == "ALLOW"
    assert store.record_delivery_evidence(
        1, attempt_token=str(token), client_correlation_id=correlation,
        outcome="ACCEPTED", provider_request_id=None,
        provider_message_id="7", reason_code=None, response_sha256="a" * 64,
        observed_at=datetime.now(timezone.utc),
    ) == str(evidence)
    assert store.mark_notification_sent(1, attempt_token=str(token), evidence_id=str(evidence))
    assert store.retry_notification_pre_submit(1, attempt_token=str(token), evidence_id=str(evidence)) == "RETRY"
    assert store.mark_notification_manual(1, attempt_token=str(token), evidence_id=str(evidence))
    assert all("bot_b59_queue_due_" in sql for sql, _ in bg.calls)
    assert "bot_b61_delivery_pre_submit" in delivery.calls[1][0]
    assert "bot_b62_transport_record_evidence" in transport.calls[0][0]


def test_hardened_factory_requires_three_explicit_urls(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://shared")
    monkeypatch.setenv("BOT_NOTIFICATION_POSTGRES_ENABLED", "1")
    monkeypatch.setenv("BOT_NOTIFICATION_B53_HARDENED_RUNTIME_ENABLED", "1")
    for key in ("BACKGROUND", "DELIVERY", "TRANSPORT"):
        monkeypatch.delenv(f"BOT_NOTIFICATION_{key}_DATABASE_URL", raising=False)
    try:
        from_environment(sqlite_path="unused")
    except RuntimeError as exc:
        assert str(exc) == "bot_notification_hardened_database_urls_missing"
    else:
        raise AssertionError("missing isolated DSNs accepted")


def test_identity_attestation_requires_exact_non_elevated_session_principal(monkeypatch):
    monkeypatch.setattr(PostgresB53HardenedBotNotificationStore, "_attest_manifest",
                        staticmethod(lambda _conn, _lane, _expected: None))
    good = {"session_name": "obsidian_exchange_bot_delivery",
            "current_name": "obsidian_exchange_bot_delivery", "rolcanlogin": True,
            "rolinherit": False, "rolsuper": False, "rolcreaterole": False,
            "rolcreatedb": False, "rolreplication": False, "rolbypassrls": False,
            "memberships": 0}
    PostgresB53HardenedBotNotificationStore._attest_connection(Conn([good]), "delivery")
    for changed in ({"session_name": "obsidian_exchange_bot_transport"}, {"rolsuper": True},
                    {"memberships": 1}, {"current_name": "obsidian_exchange_bot_delivery_owner"}):
        row = dict(good); row.update(changed)
        try:
            PostgresB53HardenedBotNotificationStore._attest_connection(Conn([row]), "delivery")
        except RuntimeError as exc:
            assert str(exc).startswith("bot_notification_identity_preflight_failed:delivery:")
        else:
            raise AssertionError(f"identity drift accepted: {changed}")


SOURCE = (ROOT / "bot/main_bot.py").read_text("utf-8")
TREE = ast.parse(SOURCE)
def node(name):
    return next(x for x in TREE.body if isinstance(x, (ast.FunctionDef, ast.AsyncFunctionDef)) and x.name == name)


class Log:
    def __getattr__(self, _): return lambda *_a, **_k: None


class Message:
    message_id = 44
    chat = type("Chat", (), {"id": 9001})()


class Bot:
    def __init__(self): self.recipients = []
    async def send_message(self, recipient, _text, **_kwargs): self.recipients.append(recipient); return Message()


class HardenedStore:
    hardened_delivery = True
    def __init__(self): self.jobs = [{"id": 7, "kind": "montera_admin", "dedupe_key": "1:9001",
        "payload": {"order_id": 1, "user_id": 101, "invoice_id": "m"}, "attempts": 1,
        "recipient_id": 9001, "attempt_token": str(uuid.uuid4())}]; self.transitions = []
    def claim_notification(self): return self.jobs.pop(0) if self.jobs else None
    def pre_submit(self, *_a, **_k): return "ALLOW"
    def record_delivery_evidence(self, *_a, **_k): return str(uuid.uuid4())
    def mark_notification_sent(self, ident, **_k): self.transitions.append(("sent", ident)); return True


def test_hardened_dispatch_sends_one_per_bound_recipient_not_live_admin_list():
    names = ("_notification_receipt_sha256", "_render_hardened_notification",
             "_dispatch_hardened_bot_notification_jobs", "_dispatch_bot_notification_jobs")
    module = ast.Module(body=[node(name) for name in names], type_ignores=[]); ast.fix_missing_locations(module)
    store, bot = HardenedStore(), Bot()
    env = {"json": __import__("json"), "hashlib": __import__("hashlib"), "uuid": uuid,
           "datetime": datetime, "timezone": timezone, "_bot_notifications": store, "bot": bot,
           "logger": Log(), "asyncio": asyncio, "ADMIN_IDS": {9001, 9002}, "_active_promos": {},
           "InlineKeyboardMarkup": lambda **k: k, "InlineKeyboardButton": lambda **k: k,
           "PUBLIC_RELAY": "https://relay.invalid", "get_cached_rate": lambda _a: 1,
           "_is_explicit_notification_failure": lambda _e: False}
    exec(compile(module, "main_bot.py", "exec"), env)
    assert asyncio.run(env["_dispatch_bot_notification_jobs"]()) == 1
    assert bot.recipients == [9001]
    assert store.transitions == [("sent", 7)]


def test_accepted_mark_failure_never_rewrites_terminal_evidence_or_resends():
    class Store(HardenedStore):
        def __init__(self): super().__init__(); self.evidence_outcomes = []
        def record_delivery_evidence(self, *_a, **kwargs):
            self.evidence_outcomes.append(kwargs["outcome"]); return str(uuid.uuid4())
        def mark_notification_sent(self, *_a, **_k): raise RuntimeError("lost mark response")
        def mark_notification_manual(self, *_a, **_k):
            raise AssertionError("accepted evidence must not become manual")
    names = ("_notification_receipt_sha256", "_render_hardened_notification",
             "_dispatch_hardened_bot_notification_jobs", "_dispatch_bot_notification_jobs")
    module = ast.Module(body=[node(name) for name in names], type_ignores=[]); ast.fix_missing_locations(module)
    store, test_bot = Store(), Bot()
    env = {"json": __import__("json"), "hashlib": __import__("hashlib"), "uuid": uuid,
           "datetime": datetime, "timezone": timezone, "_bot_notifications": store, "bot": test_bot,
           "logger": Log(), "asyncio": asyncio, "ADMIN_IDS": {9001, 9002}, "_active_promos": {},
           "InlineKeyboardMarkup": lambda **k: k, "InlineKeyboardButton": lambda **k: k,
           "PUBLIC_RELAY": "https://relay.invalid", "get_cached_rate": lambda _a: 1,
           "_is_explicit_notification_failure": lambda _e: False}
    exec(compile(module, "main_bot.py", "exec"), env)
    assert asyncio.run(env["_dispatch_bot_notification_jobs"]()) == 0
    assert test_bot.recipients == [9001]
    assert store.evidence_outcomes == ["ACCEPTED"]
