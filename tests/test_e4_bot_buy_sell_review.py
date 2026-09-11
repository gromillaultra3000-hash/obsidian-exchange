"""Actual bot handlers, inert Telegram and persistence boundaries."""
import ast
import asyncio
import importlib.util
import math
from html import escape
from pathlib import Path
from types import SimpleNamespace as NS

import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('bot_action_review',ROOT/'bot/action_review.py')
cache_module=importlib.util.module_from_spec(spec);spec.loader.exec_module(cache_module)


class State:
    def __init__(self,data): self.data=dict(data);self.current='input'
    async def get_data(self): return dict(self.data)
    async def set_data(self,data): self.data=dict(data)
    async def update_data(self,**kw): self.data.update(kw)
    async def set_state(self,value): self.current=value.state
    async def get_state(self): return self.current
    async def clear(self): self.data={};self.current=None


@pytest.fixture
def h():
    sent=[];writes=[]
    async def answer(text='',**kw): sent.append((text,kw))
    async def noop(*a,**kw): pass
    user=NS(id=7,username='synthetic')
    msg=NS(from_user=user,chat=NS(id=7),answer=answer,answer_photo=answer,edit_reply_markup=noop)
    sp=NS(refuse=lambda *a:None,label=lambda m:'СБП',bank_label=lambda b:'Банк',
          mask_details=lambda *a:'***',staff_details=lambda *a:'7900',route=lambda m:'manual')
    async def payment_kb(*a): return None
    def buy_create(**kw):
        writes.append(('buy',kw));return dict(order_id=1,agreed_rate=100,agreed_crypto_amount=10,lock_used=False,promo_used=False)
    def sell_create(**kw): writes.append(('sell',kw));return 2
    ns=dict(Message=object,FSMContext=object,CallbackQuery=object,math=math,_review_escape=escape,
            _order_reviews=cache_module.ActionReviewCache(),InlineKeyboardMarkup=lambda **kw:NS(**kw),
            InlineKeyboardButton=lambda **kw:NS(**kw),Exchange=NS(action_review=NS(state='buy-review'),payment_method=NS(state='pay')),
            Sell=NS(action_review=NS(state='sell-review')),_canonical_address=lambda c,a,**kw:a,
            _direction_open=lambda *a:True,check_order_limits=lambda uid:None,
            get_active_rate_lock=lambda *a:None,_active_promos={},get_commission_percent=lambda *a,**kw:10,
            get_rate_with_markup=lambda *a,**kw:100,_canon_network=lambda c,n:n or 'MAINNET',
            _display_destination=lambda c,a:a,_tag_name=lambda c:'',_get_bot_order_store=lambda:NS(create_order=buy_create),
            notify_admin=noop,send_sticker_safe=noop,STICKER_WAIT=None,build_payment_methods_kb=payment_kb,
            IMG_15MIN=Path('/tmp/nonexistent-e4-review-image'),_sell_payout=lambda:sp,
            sell_receive_address=lambda c:'deposit',sell_min_amount=lambda c:.01,sell_coins=lambda:['BTC'],
            get_cached_rate=lambda c:100,sell_rate_for=lambda c,m:90,sell_coin_label=lambda c:'BTC mainnet',
            sell_commission_label=lambda c:'10%',_sell_store=NS(create=sell_create),
            _sell_marker=lambda *a:'',_sell_network_hint=lambda c:' BTC',_sell_eta_text=lambda c:'после подтверждения',
            notify_admins=noop,logger=NS(error=lambda *a:None))
    tree=ast.parse((ROOT/'bot/main_bot.py').read_text())
    names={'_publish_order_review','process_order_review','_finalize_order','_finish_sell_order'}
    nodes=[n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name in names]
    for node in nodes: node.decorator_list=[]
    exec(compile(ast.Module(body=nodes,type_ignores=[]),'bot/main_bot.py','exec'),ns)
    def run(coro): return asyncio.run(coro)
    def callback(state,action='yes',token=None,uid=7):
        return NS(data='order_review_'+action+'_'+(token or state.data['_order_review_token']),
                  from_user=NS(id=uid,username='synthetic'),message=NS(**{**vars(msg),'from_user':NS(id=999,username='bot')}),answer=answer)
    def prepare(kind):
        if kind=='buy':
            state=State(dict(amount=1000,currency='BTC',network='MAINNET'))
            run(ns['_finalize_order'](msg,state,'BTC','MAINNET','addr<&>'))
        else:
            state=State(dict(sell_currency='BTC',sell_amount=1,sell_rub_amount=90,
                sell_receive_addr='deposit',sell_dest='sbp',sell_details='79001234567',sell_name='Name <&>'))
            run(ns['_finish_sell_order'](msg,state))
        return state
    return NS(**locals())


@pytest.mark.parametrize('kind',['buy','sell'])
def test_review_precedes_creation_and_binds_callback_user(h,kind):
    state=h.prepare(kind);assert h.writes==[]
    text=h.sent[-1][0]
    for required in ['ObsidianExchange','KYC','Комиссия','необратим' if kind=='sell' else 'отменить нельзя']:
        assert required in text
    assert '&lt;&amp;&gt;' in text
    cb=h.callback(state)
    h.run(h.ns['process_order_review'](cb,state))
    assert len(h.writes)==1 and h.writes[0][1]['user_id']==7
    h.run(h.ns['process_order_review'](cb,state))
    assert len(h.writes)==1


@pytest.mark.parametrize('kind',['buy','sell'])
def test_cancel_and_foreign_user_never_create(h,kind):
    state=h.prepare(kind)
    h.run(h.ns['process_order_review'](h.callback(state,uid=8),state));assert h.writes==[]
    h.run(h.ns['process_order_review'](h.callback(state,action='no'),state));assert h.writes==[]
    assert state.data=={}


@pytest.mark.parametrize('kind',['buy','sell'])
def test_silent_state_change_or_expiry_never_create(h,kind):
    state=h.prepare(kind);cb=h.callback(state)
    state.data['amount' if kind=='buy' else 'sell_details']='changed'
    h.run(h.ns['process_order_review'](cb,state));assert h.writes==[]
    state=h.prepare(kind);cb=h.callback(state)
    h.ns['_order_reviews']=cache_module.ActionReviewCache()
    h.run(h.ns['process_order_review'](cb,state));assert h.writes==[]


@pytest.mark.parametrize('kind',['buy','sell'])
def test_concurrent_callbacks_only_create_once(h,kind):
    state=h.prepare(kind);cb=h.callback(state)
    async def race(): await asyncio.gather(h.ns['process_order_review'](cb,state),h.ns['process_order_review'](cb,state))
    h.run(race());assert len(h.writes)==1


def test_closed_sell_destination_after_review_never_creates(h):
    state=h.prepare('sell');h.ns['sell_receive_address']=lambda c:'different'
    h.run(h.ns['process_order_review'](h.callback(state),state));assert h.writes==[]


def test_newer_flow_survives_stale_callback(h):
    state=h.prepare('buy');cb=h.callback(state);h.run(state.set_state(NS(state='another-flow')))
    h.run(h.ns['process_order_review'](cb,state));assert h.writes==[]
    assert state.current=='another-flow'


@pytest.mark.parametrize('action',['yes','no'])
def test_new_flow_during_callback_ack_is_preserved(h,action):
    state=h.prepare('buy');cb=h.callback(state,action=action)
    async def new_flow(*a,**kw):
        state.data={'new':'flow'};state.current='new-flow'
    cb.answer=new_flow
    h.run(h.ns['process_order_review'](cb,state))
    assert state.data=={'new':'flow'} and h.writes==[]


def test_ambiguous_buy_insert_does_not_restore_receipt(h):
    state=h.prepare('buy');cb=h.callback(state)
    def fail(**kw):
        h.writes.append(('uncertain',kw));raise RuntimeError('inert storage error')
    h.ns['_get_bot_order_store']=lambda:NS(create_order=fail)
    h.run(h.ns['process_order_review'](cb,state))
    assert 'Не повторяйте' in h.sent[-1][0]
    h.run(h.ns['process_order_review'](cb,state));assert len(h.writes)==1
