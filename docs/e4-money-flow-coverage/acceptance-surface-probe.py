"""Execute exact installed-identical site/bot entry handlers with inert boundaries."""
import ast
import asyncio
import builtins
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).parent
BOT = ROOT / 'bot/main_bot.py'
MAIN = ROOT / 'relay-fastapi/main.py'
events = []
messages = []


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HttpError(Exception):
    def __init__(self, status_code, detail):
        self.status_code = status_code


class State:
    def __init__(self, data):
        self.data = dict(data)

    async def get_data(self):
        return dict(self.data)

    async def update_data(self, **kw):
        self.data.update(kw)

    async def set_state(self, value):
        self.state = value

    async def clear(self):
        self.data.clear()


async def capture(text=None, **kw):
    messages.append({'text': text, **kw})


async def inert_async(*args, **kw):
    return None


def record(name, result):
    def call(*args, **kw):
        events.append({'boundary': name, 'messagesBefore': len(messages), 'arguments': kw})
        return result
    return call


def exact(path, names, values):
    nodes = [node for node in ast.parse(path.read_text()).body
             if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in names]
    assert len(nodes) == len(names)
    for node in nodes:
        node.decorator_list = []
    tree = ast.Module(body=[ast.ImportFrom(module='__future__', names=[ast.alias(name='annotations')], level=0), *nodes], type_ignores=[])
    exec(compile(ast.fix_missing_locations(tree), str(path), 'exec'), values)
    return values


def imports(mapping):
    def load(name, globals=None, locals=None, fromlist=(), level=0):
        if name == '__future__':
            return builtins.__import__(name, globals, locals, fromlist, level)
        if name not in mapping:
            raise AssertionError('Unexpected import: ' + name)
        return mapping[name]
    return {**vars(builtins), '__import__': load}


def clean():
    events.clear()
    messages.clear()


async def run():
    cases = []
    fixture_user = {'telegram_id': 420001, 'id': 730001, 'email': 'synthetic@example.invalid'}
    auth_state = {'user': fixture_user, 'csrf': True}
    validator = {'address': True, 'owns': True}
    service = NS(create_session=record('payment_service.create_session', {'session_token': 'synthetic-only-session'}))
    site = exact(MAIN, {'dashboard_exchange_submit'}, {
        '__builtins__': imports({'services.payment_service': NS(PaymentService=lambda **kw: service)}),
        'Form': lambda value: value,
        'auth': NS(get_web_user=lambda request: auth_state['user'], verify_csrf=lambda *args: auth_state['csrf']),
        'RedirectResponse': lambda url, status_code: {'redirect': url, 'status': status_code},
        'HTTPException': HttpError,
        '_assets': NS(normalize_network=lambda *args: 'BTC'),
        '_allowed_currencies': lambda: ['BTC'], '_is_offered': lambda *args: True,
        'MIN_AMOUNT': 2000, 'MAX_AMOUNT': 500000,
        'exchange_calc': NS(validate_crypto_address=lambda *args: validator['address'], get_rate_with_markup=lambda *args: 1000000),
        '_resolve_destination': lambda currency, address, *args, **kw: (address, None),
        '_is_true': bool,
        'templates': NS(TemplateResponse=lambda *args, **kw: {'render': args[1], 'status': kw.get('status_code', 200)}),
        'site_context': lambda *args, **kw: kw,
        '_order_store': NS(create=record('order_store.create', 101)),
        'ADMIN_ID': None, 'audit_log': lambda *args: None,
        'logger': NS(error=lambda *args: None),
    })
    request = NS(client=NS(host='192.0.2.1'))
    async def submit():
        return await site['dashboard_exchange_submit'](request, 'synthetic-csrf', 'BTC', 2000, 'synthetic-owned-destination', 'sbp', 'BTC', '', '')
    auth_state['user'] = None
    response = await submit()
    assert response['redirect'] == '/login' and not events
    cases.append({'name': 'site-unauthenticated-redirect-before-effects', 'result': 'PASS'})
    auth_state['user'] = fixture_user
    auth_state['csrf'] = False
    try:
        await submit()
        raise AssertionError('CSRF accepted')
    except HttpError as exc:
        assert exc.status_code == 403 and not events
    cases.append({'name': 'site-csrf-denial-before-effects', 'result': 'PASS'})
    auth_state['csrf'] = True
    validator['address'] = False
    response = await submit()
    assert response['status'] == 400 and not events
    cases.append({'name': 'site-invalid-destination-before-effects', 'result': 'PASS'})
    validator['address'] = True
    response = await submit()
    assert response['redirect'] == '/pay/synthetic-only-session'
    assert [e['boundary'] for e in events] == ['order_store.create', 'payment_service.create_session']
    cases.append({'name': 'site-valid-form-orders-before-payment-session', 'result': 'PASS',
                  'observedBoundaries': list(events), 'interpretation': 'A form submit creates an order and payment intent; this inert probe does not transfer funds or establish human confirmation adequacy.'})
    clean()
    message = NS(from_user=NS(id=420001, username='synthetic'), chat=NS(id=420001),
                 answer=capture, edit_reply_markup=inert_async)
    callback = NS(data='useaddr_0', from_user=message.from_user, message=message, answer=capture)
    bot = exact(BOT, {'process_saved_address', 'process_address', '_finalize_order'}, {
        '__builtins__': imports({'core': NS(address_book=NS(owns=lambda *args: validator['owns']))}),
        'sys': NS(path=['synthetic-relay']), 'RELAY_PATH': 'synthetic-relay',
        'logger': NS(exception=lambda *args: None),
        'validate_crypto_address': lambda *args: validator['address'],
        '_direction_open': lambda *args: True,
        '_canonical_address': lambda currency, address, **kw: address,
        '_tag_name': lambda *args: None, '_network_label': lambda *args: 'Bitcoin',
        'check_order_limits': lambda *args: None, 'get_active_rate_lock': lambda *args: None,
        '_active_promos': {}, 'get_commission_percent': lambda *args, **kw: 10,
        'get_rate_with_markup': lambda *args, **kw: 1000000,
        '_get_bot_order_store': lambda: NS(create_order=record('bot_order_store.create_order', {
            'order_id': 102, 'agreed_rate': 1000000, 'agreed_crypto_amount': .002, 'promo_used': False})),
        '_canon_network': lambda currency, network: network,
        'notify_admin': inert_async, 'send_sticker_safe': inert_async, 'STICKER_WAIT': None,
        'Exchange': NS(payment_method='payment_method'),
        'build_payment_methods_kb': inert_async, 'IMG_15MIN': NS(exists=lambda: False),
    })
    state_data = {'currency': 'BTC', 'network': 'BTC', 'amount': 2000, 'addr_book': ['synthetic-owned-destination']}
    validator['owns'] = False
    await bot['process_saved_address'](callback, State(state_data))
    assert not events and 'Адрес не подтвердился' in messages[0]['text']
    cases.append({'name': 'bot-foreign-saved-destination-denied-before-effects', 'result': 'PASS'})
    clean()
    validator['owns'] = True
    callback.data = 'useaddr_99'
    await bot['process_saved_address'](callback, State(state_data))
    assert not events and 'устарела' in messages[0]['text']
    cases.append({'name': 'bot-stale-saved-destination-denied-before-effects', 'result': 'PASS'})
    clean()
    callback.data = 'useaddr_0'
    await bot['process_saved_address'](callback, State(state_data))
    assert len(events) == 1 and events[0]['arguments']['user_id'] == 420001
    order_card = messages[-1]['text']
    assert 'Заявка #102 создана' in order_card and 'Комиссия' in order_card
    assert 'synthetic-owned-destination' not in order_card and 'Сеть:' not in order_card
    cases.append({'name': 'bot-owned-saved-address-creates-pending-order-before-payment-method', 'result': 'PASS',
                  'observedBoundaries': list(events), 'orderCard': order_card,
                  'coverageFact': 'Generated order card shows amount, receive estimate and commission; it omits full recipient address/network. Address selection creates a pending order, not a fund transfer. Human adequacy and recipient review are not established.'})
    clean()
    validator['address'] = False
    message.text = 'synthetic-invalid-destination'
    await bot['process_address'](message, State(state_data))
    assert not events and 'Адрес не принят' in messages[0]['text']
    cases.append({'name': 'bot-invalid-typed-destination-denied-before-effects', 'result': 'PASS'})

    files = ['bot/main_bot.py', 'relay-fastapi/main.py', 'relay-fastapi/templates/index.html',
             'relay-fastapi/templates/dashboard_exchange.html', 'relay-fastapi/templates/dashboard_sell.html',
             'relay-fastapi/templates/dashboard_swap.html', 'relay-fastapi/templates/rates.html']
    installed = []
    for name in files:
        live = Path('/opt/obsidian-exchange') / name
        assert sha(ROOT / name) == sha(live), name
        installed.append({'path': str(live), 'sha256': sha(live)})
    report = {
        'schemaVersion': 'e4-money-flow-site-bot-exact-entry-acceptance.v1', 'result': 'PASS',
        'route': 'E4 / MONEY_FLOW_ACCEPTANCE_COVERAGE', 'count': len(cases), 'cases': cases,
        'method': 'AST-extracted exact site/bot handlers; decorators alone stripped, deferred annotations. No whole runtime imports. Auth/user/address/rate boundaries are synthetic; persistence/payment/admin/message boundaries are inert captures.',
        'realDatabaseProviderMessageWalletServiceOperations': 0,
        'coverageGap': 'Existing E4 bot/site entry tests assert links and source strings. They do not execute these handler authorization, recipient-validation or pre-payment ordering paths. This probe adds bounded exact execution while leaving product unchanged.',
        'limits': [
            'Address ownership, validation and rate helpers are injected outcomes; this is not a cryptographic address or database authorization proof.',
            'Captured effect boundaries are observations, not real writes or provider invocations.',
            'No claim that pending order creation is an irreversible money transfer or that all bot flows are covered.',
            'Real Telegram layout, platform behavior and human comprehension remain unverified.'
        ],
        'installedInputs': installed,
        'inputs': [{'path': name, 'sha256': sha(ROOT / name)} for name in files + [str(Path(__file__).relative_to(ROOT))]],
    }
    (OUT / 'acceptance-surface-probe.json').write_text(json.dumps(report, indent=2, ensure_ascii=False) + '\n')
    print(json.dumps({'result': 'PASS', 'cases': len(cases), 'realEffects': 0}))


if __name__ == '__main__':
    asyncio.run(run())
