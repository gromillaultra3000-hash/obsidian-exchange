'use strict';
const fs = require('node:fs');
const vm = require('node:vm');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const sourcePath = '/root/output/manual/e4-activity-deadline-20260908/baseline-webapp.html';
const source = fs.readFileSync(sourcePath, 'utf8');
const begin = source.indexOf('        let historyOrders =');
const end = source.indexOf('        (function wireHistoryControls()', begin);
const eb = source.indexOf('        function esc(s) {');
const ee = source.indexOf('        async function loadWalletBook()', eb);
const exact = source.slice(eb, ee) + source.slice(begin, end);
const flush = async () => {for (let n = 0; n < 8; n++) await Promise.resolve();};
async function reproduce(mode) {
    const nodes = new Map(['history-list','history-summary','history-load-status','ecosystem-activity-status'].map(id => [id,
        {innerHTML:'',textContent:'',style:{},attributes:{},querySelectorAll:()=>[],setAttribute(name,value){this.attributes[name]=value;}}]));
    const requests=[], timers=[];
    const ctx=vm.createContext({document:{getElementById:id=>nodes.get(id),querySelectorAll:()=>[]},
        tg:{initData:''},userId:'synthetic-user',location:{origin:'https://acceptance.invalid'},
        setTimeout:(callback,ms)=>{timers.push({callback,ms});return timers.length;},clearTimeout(){},
        fetch:(url,options)=>new Promise((resolve,reject)=>requests.push({url,options,resolve,reject}))});
    vm.runInContext(exact,ctx);
    let settled=false;
    const read=ctx.loadHistory(); read.then(()=>{settled=true;});
    if(mode==='body') requests[0].resolve({ok:true,json:()=>new Promise(()=>{})});
    await flush();
    // Advance all deadlines registered by the exact loader through 30 seconds.
    // The original helper schedules none, so a stalled read has no deadline.
    for(const timer of timers) if(timer.ms<=30000) timer.callback();
    await flush();
    ctx.setHistoryFilter('pending');
    const observation={settled,scheduledDeadlines:timers.map(t=>t.ms),
        requestHasAbortSignal:!!requests[0].options.signal,
        loadState:vm.runInContext('historyLoadState',ctx),
        ariaBusy:nodes.get('history-list').attributes['aria-busy'],
        loadStatus:nodes.get('history-load-status').textContent,
        overview:nodes.get('ecosystem-activity-status').textContent,
        filter:vm.runInContext('historyFilter',ctx)};
    assert.equal(settled,false);assert.equal(timers.length,0);assert.equal(observation.ariaBusy,'true');
    const retry=ctx.loadHistory();
    requests[1].resolve({ok:true,json:async()=>[]});await retry;
    assert.equal(vm.runInContext('historyLoadState',ctx),'ready');
    return {mode,afterScheduledDeadlinesThroughMs:30000,observation,
        explicitRetryRecovers:true,stalledOriginalStillUnsettled:!settled};
}
(async()=>{
 const report={schemaVersion:'e4-activity-deadline-acceptance-baseline.v1',recordedAt:new Date().toISOString(),
  reviewer:'Codex independent context-aware acceptance /root/support_acceptance',
  route:'E4 / ACTIVITY_REFRESH_DEADLINE / bound the latest activity read across fetch and response-body stalls, preserve explicit retry',
  canonicalCriterion:'E4 unified notification/evidence/support centre and accessibility/usability of monetary paths',
  result:'BASELINE_STALL_REPRODUCED',sourcePath,sourceSha256:crypto.createHash('sha256').update(source).digest('hex'),
  method:'Exact shipped activity helpers in Node VM with synthetic unresolved fetch or JSON-body promise and an instrumented timer scheduler. No real network, account data, navigation or money action.',
  observedBehavior:'Latest activity fetch or JSON body can remain unresolved with aria-busy=true and updating statuses. The helper supplies no abort signal and schedules no deadline. Explicit retry can recover, but no bounded unavailable/retry transition exists for the stalled latest invocation.',
  reproduction:[await reproduce('fetch'),await reproduce('body')],
  boundedImplementation:'Add a source-owned deadline spanning fetch and body parsing, cancel/retire obsolete work safely, show truthful unavailable/retry state for latest timeout, and preserve latest-request/filter semantics. Verify both synthetic completion races and isolated real-browser fetch/body behavior without new writers.',
  currentSliceDisposition:'Independent original-state evidence for the current ACTIVITY_REFRESH_DEADLINE implementation.',
  limitations:['The 30-second scheduler horizon is simulated, not an elapsed real-network claim. There are no timers to trigger in the current helper.','This evidence cannot establish native browser streaming-body timeout, real Telegram/iOS behavior, or provider availability.','No E4 gate closure or earlier-stage advancement is implied.']};
 fs.writeFileSync('/root/output/playwright/e4-activity-deadline-20260908/acceptance/baseline.json',JSON.stringify(report,null,2)+'\n');
 console.log(JSON.stringify({result:report.result,sourceSha256:report.sourceSha256,reproduction:report.reproduction},null,2));
})();
