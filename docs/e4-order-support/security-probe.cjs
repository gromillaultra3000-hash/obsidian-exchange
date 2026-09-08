'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const crypto = require('node:crypto');
const sourcePath = '/root/relay/webapp.html';
const source = fs.readFileSync(sourcePath, 'utf8');
const copyBegin = source.indexOf('        let orderIdCopyPending =');
const copyEnd = source.indexOf('        function renderHistoryOrders()', copyBegin);
const openBegin = source.indexOf('        function openSupport()');
const openEnd = source.indexOf('        function openBotSwap()', openBegin);
assert.ok(copyBegin > 0 && copyEnd > copyBegin && openBegin > 0 && openEnd > openBegin);
const helpers = source.slice(copyBegin, copyEnd) + source.slice(openBegin, openEnd);
function setup(clipboard, telegram = true) {
  const cards = new Set(), opens = [], writes = [], haptics = [];
  const list = {contains: button => cards.has(button), querySelectorAll: () => [...cards].map(button => button.parentElement.querySelector()).filter(status => status.dataset.copyWaiting)};
  const nav = {};
  if (clipboard !== undefined) Object.defineProperty(nav, 'clipboard', {get: () => typeof clipboard === 'function' ? clipboard() : clipboard});
  const tg = {HapticFeedback: {notificationOccurred(kind) {haptics.push(kind); throw new Error('synthetic haptic throw');}}};
  if (telegram) tg.openTelegramLink = (...args) => opens.push({kind:'telegram', args});
  const context = vm.createContext({document:{getElementById: id => id === 'history-list' ? list : null}, navigator:nav,
    window:{isSecureContext:true, open:(...args)=>opens.push({kind:'browser', args})}, tg});
  vm.runInContext(helpers, context);
  const card = () => {
    const status = {textContent:'initial', isConnected:true, dataset:{}};
    const button = {disabled:false, parentElement:{querySelector:()=>status}};
    cards.add(button);
    return {button,status,detach(){cards.delete(button); status.isConnected=false;}};
  };
  return {context, card, opens, writes, haptics};
}
async function main() {
  const checks=[];
  for (const telegram of [true,false]) {
    const env = setup(() => {throw new Error('clipboard must not be consulted');}, telegram);
    const result = env.context.openOrderSupport('ORDER-PRIVATE', {dataset:{orderId:'ORDER-PRIVATE'}});
    assert.equal(result, undefined);
    assert.deepEqual(env.opens, [{kind:telegram?'telegram':'browser', args:telegram?['https://t.me/ObsidianSupBot']:['https://t.me/ObsidianSupBot','_blank','noopener']}]);
    checks.push(telegram?'same_turn_telegram_fixed_no_payload':'same_turn_browser_fixed_no_payload');
  }
  for (const failure of ['absent','no_method','getter_throw','method_throw','rejected','insecure']) {
    const clipboard = failure === 'absent' ? undefined : failure === 'no_method' ? {} : failure === 'getter_throw' ? () => {throw new Error('private diagnostic');} : {writeText() {
      if (failure === 'method_throw') throw new Error('private diagnostic');
      return Promise.reject(new Error('private diagnostic'));
    }};
    const env=setup(clipboard), row=env.card();
    if (failure === 'insecure') env.context.window.isSecureContext=false;
    const promise=env.context.copyOrderId('ORDER-SYNTHETIC',row.button);
    env.context.openOrderSupport();
    assert.equal(env.opens.length,1);
    assert.equal(await promise,false);
    assert.match(row.status.textContent,/Не удалось скопировать номер/);
    assert.equal(row.status.textContent.includes('private diagnostic'),false);
    assert.equal(row.button.disabled,false);
    assert.equal(env.haptics.length,0);
    checks.push(failure+'_honest_failure_support_independent');
  }
  {
    const pending=[], writes=[];
    const env=setup({writeText(value){writes.push(value); return new Promise((resolve,reject)=>pending.push({resolve,reject}));}});
    const first=env.card(), second=env.card();
    const oldPromise=env.context.copyOrderId('ORDER-A',first.button);
    env.context.openOrderSupport();
    assert.equal(env.opens.length,1);
    assert.equal(first.button.disabled,true);
    assert.match(first.status.textContent,/Копируем номер/);
    assert.equal(await env.context.copyOrderId('ORDER-B',second.button),false);
    assert.equal(writes.length,1);
    assert.match(second.status.textContent,/Предыдущее копирование/);
    const oldStatus=first.status.textContent;
    first.detach();
    assert.equal(await env.context.copyOrderId('ORDER-A',first.button),false);
    pending[0].resolve();
    assert.equal(await oldPromise,true);
    assert.equal(first.status.textContent,oldStatus);
    assert.match(second.status.textContent,/Теперь можно скопировать/);
    assert.equal(second.status.dataset.copyWaiting,undefined);
    assert.equal(env.haptics.length,0);
    assert.equal(writes.length,1);
    const nextPromise=env.context.copyOrderId('ORDER-B',second.button);
    assert.deepEqual(writes,['ORDER-A','ORDER-B']);
    pending[1].resolve();
    assert.equal(await nextPromise,true);
    assert.match(second.status.textContent,/Номер скопирован/);
    assert.equal(second.button.disabled,false);
    assert.equal(env.haptics.length,1);
    checks.push('stalled_serialization_detach_waiting_cleared_no_autocopy_fresh_retry_haptic_throw');
  }
  {
    let copied;
    const env=setup({writeText(value){copied=value; return Promise.resolve();}}), row=env.card();
    const literal='ORDER-\'"<&> ${neverExecute} `neverExecute`';
    assert.equal(await env.context.copyOrderId(literal,row.button),true);
    assert.equal(copied,literal);
    assert.equal(env.opens.length,0);
    checks.push('copy_is_literal_local_explicit_and_support_not_opened');
  }
  return {reviewer:'/root/support_security',node:process.version,source:sourcePath,sourceSha256:crypto.createHash('sha256').update(source).digest('hex'),status:'PASS',checks,
    scope:'Synthetic VM only; no network, Telegram invocation, database, money, service mutation, or 064A operation.'};
}
main().then(result=>process.stdout.write(JSON.stringify(result,null,2)+'\n')).catch(error=>{console.error(error);process.exitCode=1;});
