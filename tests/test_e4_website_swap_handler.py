"""Actual handler with inert auth/provider/persistence boundaries."""
import ast
import asyncio
import importlib.util
from pathlib import Path
import sys
from types import ModuleType, SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('site_swap_review', ROOT / 'relay-fastapi/swap_review.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


@pytest.fixture
def harness(monkeypatch):
    calls = []
    user = dict(id=1, telegram_id=None, session_token='synthetic-session', csrf_token='csrf')
    provider = ModuleType('providers.swapuz')
    class Provider:
        def get_rate(self, *args):
            calls.append('quote')
            return dict(estimated_receive=2, rate=20, min_amount=.01, max_amount=1, withdraw_fee=0)
        def create_swap(self, **kwargs):
            calls.append('create')
            return dict(uid='synthetic', url='https://example.invalid', deposit_address='deposit')
    provider.SwapUzProvider = Provider
    provider.SWAPUZ_NETWORKS = dict(BTC='BTC', LTC='LTC')
    monkeypatch.setitem(sys.modules, 'providers.swapuz', provider)
    tokens = ModuleType('utils.tokens')
    tokens.generate_session_token = lambda: 'synthetic-order'
    monkeypatch.setitem(sys.modules, 'utils.tokens', tokens)
    def render(request, template, context, status_code=200, headers=None):
        return SimpleNamespace(template=template, context=context, status_code=status_code, headers=headers)
    class HttpError(Exception):
        def __init__(self, status_code, detail): self.status_code = status_code
    ns = dict(Request=object, Form=lambda x:x, HTMLResponse=object,
              auth=SimpleNamespace(get_web_user=lambda r:user, verify_csrf=lambda u,t:t=='csrf'),
              templates=SimpleNamespace(TemplateResponse=render),
              site_context=lambda request, **kw:kw, HTTPException=HttpError,
              RedirectResponse=lambda url,status_code:SimpleNamespace(url=url,status_code=status_code),
              exchange_calc=SimpleNamespace(SWAP_COINS=['BTC','LTC'],validate_crypto_address=lambda a,c:a=='address'),
              _swap_reviews=module.SwapReviewCache(), asyncio=asyncio, math=__import__('math'), logger=SimpleNamespace(error=lambda *args:None),
              _swap_store=SimpleNamespace(create=lambda **kw:calls.append('persist')),
              audit_log=lambda *args:None)
    tree = ast.parse((ROOT/'relay-fastapi/main.py').read_text())
    node = next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='dashboard_swap_submit')
    node.decorator_list=[]
    exec(compile(ast.Module(body=[node],type_ignores=[]),str(ROOT/'relay-fastapi/main.py'),'exec'),ns)
    def call(**kw):
        args=dict(request=SimpleNamespace(url=SimpleNamespace(path='/dashboard/swap/confirm' if kw.get('review_action','quote')!='quote' else '/dashboard/swap')),csrf_token='csrf',coin_from='BTC',coin_to='LTC',amount=.1,address='address')
        args.update(kw)
        return asyncio.run(ns['dashboard_swap_submit'](**args))
    return SimpleNamespace(call=call,calls=calls,user=user,provider=Provider,ns=ns)


def test_quote_then_deliberate_confirmation_and_replay(harness):
    h=harness; r=h.call()
    assert r.template=='dashboard_swap_review.html' and h.calls==['quote']
    token=r.context['review']['token']
    assert h.call(review_action='confirm',review_token=token).status_code==400
    assert h.calls==['quote']
    assert h.call(review_action='confirm',review_ack='1',review_token=token).url=='/swap/synthetic-order'
    assert h.calls==['quote','create','persist']
    assert h.call(review_action='confirm',review_ack='1',review_token=token).status_code==409
    assert h.calls==['quote','create','persist']


@pytest.mark.parametrize('change',[dict(amount=.2),dict(coin_from='LTC',coin_to='BTC')])
def test_changed_fields_never_create(harness,change):
    h=harness; token=h.call().context['review']['token']
    assert h.call(review_action='confirm',review_ack='1',review_token=token,**change).status_code==409
    assert h.calls==['quote']


def test_other_session_and_edit_never_create(harness):
    h=harness; token=h.call().context['review']['token']; h.user['session_token']='other'
    assert h.call(review_action='confirm',review_ack='1',review_token=token).status_code==409
    h.user['session_token']='synthetic-session'
    assert h.call(review_action='edit',review_token=token).status_code==200
    assert h.call(review_action='confirm',review_ack='1',review_token=token).status_code==409
    assert h.calls==['quote']


@pytest.mark.parametrize('amount',[float('nan'),float('inf'),0,-1])
def test_invalid_amount_has_no_provider_effect(harness,amount):
    assert harness.call(amount=amount).status_code==400
    assert harness.calls==[]


def test_csrf_precedes_provider(harness):
    with pytest.raises(harness.ns['HTTPException']): harness.call(csrf_token='bad')
    assert harness.calls==[]


def test_uncertain_submit_consumes_receipt(harness):
    h=harness; token=h.call().context['review']['token']
    def unknown(self,**kwargs):
        h.calls.append('create'); raise TimeoutError()
    h.provider.create_swap=unknown
    assert h.call(review_action='confirm',review_ack='1',review_token=token).status_code==502
    assert h.call(review_action='confirm',review_ack='1',review_token=token).status_code==409
    assert h.calls==['quote','create']


def test_persistence_failure_never_retries_provider(harness):
    h=harness; token=h.call().context['review']['token']
    def fail(**kw): raise RuntimeError('synthetic storage failure')
    h.ns['_swap_store'].create=fail
    response=h.call(review_action='confirm',review_ack='1',review_token=token)
    assert response.status_code==502 and 'Код обращения' in response.context['error']
    assert h.call(review_action='confirm',review_ack='1',review_token=token).status_code==409
    assert h.calls==['quote','create']


def test_quote_alias_is_registered_and_new_forms_are_rollback_safe(harness):
    text=(ROOT/'relay-fastapi/main.py').read_text()
    assert '@app.post("/dashboard/swap/quote"' in text
    assert 'action="/dashboard/swap/quote"' in (ROOT/'relay-fastapi/templates/dashboard_swap.html').read_text()
    request=SimpleNamespace(url=SimpleNamespace(path='/dashboard/swap/quote'))
    assert harness.call(request=request).template=='dashboard_swap_review.html'
    assert harness.calls==['quote']
