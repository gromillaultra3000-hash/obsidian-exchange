import ast
import asyncio
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SOURCE = (ROOT / "bot/main_bot.py").read_text("utf-8")
TREE = ast.parse(SOURCE)


def node(name):
    return next(item for item in TREE.body
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
                and item.name == name)


PRODUCERS = {
    "recall_inactive_users": "queue_due_recalls",
    "montera_receipt_reminder": "queue_due_montera",
    "abandoned_order_reminder": "queue_due_abandoned",
    "payout_delay_notice_task": "queue_due_payout_delays",
    "winback_promo_task": "queue_due_winbacks",
}
for name, call in PRODUCERS.items():
    body = ast.get_source_segment(SOURCE, node(name))
    assert f"_bot_notifications.{call}(" in body, (name, call)
    for forbidden in ("db_conn(", ".execute(", "sent_notifications", "issue_winback(",
                      "_pq.queue("):
        # Docstrings may explain marker semantics; executable SQL/calls may not.
        executable = "\n".join(line for line in body.splitlines()
                               if not line.lstrip().startswith(('"', "'")))
        if forbidden == "sent_notifications":
            executable = ast.dump(node(name), include_attributes=False)
            # Constants (the docstring) are deliberately ignored.
            executable = " ".join(part for part in executable.split("Constant(value=")
                                  if not part.startswith(("'", '"')))
        assert forbidden not in executable, (name, forbidden)

assert "_bot_notifications = _bot_notification_store_module.from_environment(" in SOURCE
assert "create_task(bot_notification_dispatcher())" in SOURCE


class Log:
    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


class Store:
    def __init__(self, jobs):
        self.jobs = list(jobs)
        self.sent = []
        self.retried = []

    def claim_notification(self):
        return self.jobs.pop(0) if self.jobs else None

    def mark_notification_sent(self, ident):
        self.sent.append(ident)
        return True

    def retry_notification(self, ident):
        self.retried.append(ident)
        return True


class Bot:
    def __init__(self, failure=None):
        self.messages = []
        self.failure = failure

    async def send_message(self, recipient, text, **kwargs):
        if self.failure:
            failure = self.failure(recipient, len(self.messages))
            if failure:
                raise failure
        self.messages.append((recipient, text, kwargs))


def markup(**kwargs):
    return kwargs


jobs = [
    {"id": 1, "kind": "recall", "payload": {"user_id": 101}},
    {"id": 2, "kind": "montera_customer", "payload": {
        "order_id": 201, "user_id": 102, "invoice_id": "m-201", "has_file": True}},
    {"id": 3, "kind": "montera_admin", "payload": {
        "order_id": 201, "user_id": 102, "invoice_id": "m-201", "has_file": True}},
    {"id": 4, "kind": "pay_reminder", "payload": {
        "order_id": 301, "user_id": 103, "rub_amount": 12500, "currency": "LTC",
        "session_token": "live-token"}},
    {"id": 5, "kind": "payout_delayed", "payload": {
        "order_id": 401, "user_id": 104, "currency": "BTC"}},
    {"id": 6, "kind": "winback_promo", "payload": {
        "order_id": 501, "user_id": 105, "code": "BACK5-ABCDEF", "code_id": 77,
        "discount": 5, "valid_hours": 72}},
]
store = Store(jobs)
bot = Bot()
active = {}
module = ast.Module(body=[node("_dispatch_bot_notification_jobs")], type_ignores=[])
ast.fix_missing_locations(module)
env = {
    "_bot_notifications": store,
    "bot": bot,
    "get_cached_rate": lambda currency: {"BTC": 100000, "LTC": 10000, "USDT": 100}[currency],
    "InlineKeyboardMarkup": markup,
    "InlineKeyboardButton": markup,
    "PUBLIC_RELAY": "https://relay.example",
    "ADMIN_IDS": (9001, 9002),
    "_active_promos": active,
    "_is_explicit_notification_failure": lambda _exc: False,
    "logger": Log(),
    "asyncio": asyncio,
}
exec(compile(module, "main_bot.py", "exec"), env)
assert asyncio.run(env["_dispatch_bot_notification_jobs"]()) == 6
assert store.sent == [1, 2, 3, 4, 5, 6] and store.retried == []
assert [recipient for recipient, _, _ in bot.messages] == [
    101, 102, 9001, 9002, 103, 104, 105]
assert bot.messages[0][1] == (
    "🟣 <b>ObsidianExchange — актуальные курсы</b>\n\n"
    "<blockquote>₿ BTC → 81 000 ₽\nŁ LTC → 8 100 ₽\n💵 USDT → 98 ₽</blockquote>\n\n"
    "Готовы к обмену? Нажмите кнопку ниже 👇")
assert bot.messages[1][1] == (
    "⏰ <b>Заявка #201 — осталось ~10 минут!</b>\n\n"
    "Мы получили ваш файл, но платёжный партнёр принимает только <b>PDF-чек из банка</b> "
    "— фото и скриншоты он не читает.\nПришлите PDF сюда, иначе заявку придётся "
    "разбирать вручную.")
assert bot.messages[2][1] == bot.messages[3][1] == (
    "⚠️ <b>Заявка #201</b> — чек не отправлен, дедлайн через ~10 мин\n"
    "Montera ID: <code>m-201</code>")
assert bot.messages[4][1] == (
    "⏳ <b>Заявка #301 ждёт оплаты</b>\n\n"
    "12 500 ₽ → LTC. Курс ещё зафиксирован, но скоро истечёт.\n"
    "Оплатите, чтобы получить крипту по текущему курсу. 🟣")
assert bot.messages[4][2]["reply_markup"]["inline_keyboard"][0][0]["url"] == (
    "https://relay.example/pay/live-token")
assert bot.messages[5][1] == (
    "⏳ <b>Заявка #401 — выплата задерживается</b>\n\n"
    "Ваша оплата получена и подтверждена, деньги у нас. Отправку BTC задерживает "
    "ручная проверка — заявкой уже занимается сотрудник.\n\nНичего делать не нужно "
    "и повторно платить не нужно. Как только крипта уйдёт, вы получите здесь номер "
    "транзакции в блокчейне.")
assert bot.messages[6][1] == (
    "🎁 <b>Персональная скидка −5% на обмен</b>\n\n"
    "Ваша заявка истекла, и мы хотим предложить условия лучше: скидка <b>уже "
    "активирована</b> — просто создайте новую заявку в течение 72 часов.\n\n"
    "Промокод на всякий случай: <code>/promo BACK5-ABCDEF</code>")
assert active == {105: (77, 5.0)}


class ExplicitFailure(Exception):
    pass


# Telegram explicitly rejected the call: no delivery occurred, retry is safe.
store = Store([{"id": 10, "kind": "payout_delayed", "payload": {
    "order_id": 601, "user_id": 106, "currency": "BTC"}}])
env["_bot_notifications"] = store
env["bot"] = Bot(lambda _recipient, _count: ExplicitFailure("rejected"))
env["_is_explicit_notification_failure"] = lambda exc: isinstance(exc, ExplicitFailure)
assert asyncio.run(env["_dispatch_bot_notification_jobs"]()) == 0
assert store.retried == [10] and store.sent == []

# A transport exception after the send began is ambiguous and remains claimed.
store = Store([{"id": 11, "kind": "payout_delayed", "payload": {
    "order_id": 602, "user_id": 107, "currency": "LTC"}}])
env["_bot_notifications"] = store
env["bot"] = Bot(lambda _recipient, _count: RuntimeError("connection reset"))
env["_is_explicit_notification_failure"] = lambda _exc: False
assert asyncio.run(env["_dispatch_bot_notification_jobs"]()) == 0
assert store.retried == [] and store.sent == []

# A group-admin job cannot be retried after one recipient succeeded, even when
# the second recipient returns an explicit rejection: retry would duplicate #1.
store = Store([{"id": 12, "kind": "montera_admin", "payload": {
    "order_id": 603, "user_id": 108, "invoice_id": "m-603", "has_file": False}}])
env["_bot_notifications"] = store
env["bot"] = Bot(lambda recipient, _count: ExplicitFailure("rejected")
                 if recipient == 9002 else None)
env["_is_explicit_notification_failure"] = lambda exc: isinstance(exc, ExplicitFailure)
assert asyncio.run(env["_dispatch_bot_notification_jobs"]()) == 0
assert env["bot"].messages[0][0] == 9001
assert store.retried == [] and store.sent == []

helper = ast.get_source_segment(SOURCE, node("_is_explicit_notification_failure"))
assert "TelegramNetworkError" not in helper and "TelegramServerError" not in helper
assert "TelegramRetryAfter" in helper and "TelegramBadRequest" in helper

print("Bot notification adapter/text/outcome checks: OK")
