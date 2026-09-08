'use strict';
const fs=require('node:fs'),vm=require('node:vm'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const out='/root/output/playwright/e4-activity-deadline-20260908/acceptance';
const sourcePath='/root/relay/webapp.html';
const source=fs.readFileSync(sourcePath,'utf8');
const backend=JSON.parse(fs.readFileSync(out+'/next-prerequisite-backend.json','utf8'));
const start=source.indexOf('        let historyOrders =');
const end=source.indexOf('        (function wireHistoryControls()',start);
const eb=source.indexOf('        function esc(s) {'),ee=source.indexOf('        async function loadWalletBook()',eb);
const exact=source.slice(eb,ee)+source.slice(start,end);
const results=[];
for(const fixture of backend.results){
 const nodes=new Map(['history-list','history-summary','history-load-status','ecosystem-activity-status'].map(id=>[id,
  {innerHTML:'',textContent:'',style:{},setAttribute(){},querySelectorAll(){return[];}}]));
 const ctx=vm.createContext({document:{getElementById:id=>nodes.get(id)},location:{origin:'https://acceptance.invalid'},__fixture:fixture.apiResponse});
 vm.runInContext(exact,ctx);vm.runInContext("historyOrders=__fixture;historyLoadState='ready';renderHistoryOrders();",ctx);
 const markup=nodes.get('history-list').innerHTML;
 const evidence=markup.match(/class="history-evidence"[^>]*>(.*?)<\/div>/)?.[1]||'';
 results.push({case:fixture.case,status:fixture.apiResponse[0].status,receipt:fixture.apiResponse[0].receipt,
  backendTxUrl:fixture.apiResponse[0].tx_url,visibleReceiptEvidence:evidence,
  showsCompletedStatus:markup.includes('Отправлено'),showsClosedStatus:markup.includes('Заявка отменена'),
  transactionActionPresent:markup.includes('🔍 Транзакция'),
  transactionEvidenceExplanationPresent:markup.includes('Доказательство выдачи — ссылка на транзакцию выше.'),
  promisesFutureReceiptStatus:evidence.includes('Его статус появится здесь.')});
}
assert.match(results[0].visibleReceiptEvidence,/Чек передан на проверку/);
assert.equal(results[1].showsCompletedStatus,true);assert.equal(results[1].transactionActionPresent,true);
assert.equal(results[1].transactionEvidenceExplanationPresent,false);
assert.equal(results[2].showsCompletedStatus,true);assert.equal(results[2].promisesFutureReceiptStatus,true);
assert.equal(results[3].showsClosedStatus,true);assert.equal(results[3].promisesFutureReceiptStatus,true);
const report={schemaVersion:'e4-activity-receipt-evidence-next-prerequisite.v1',recordedAt:new Date().toISOString(),
 reviewer:'Codex independent context-aware acceptance /root/support_acceptance',
 nextCanonicalItem:'E4 / ACTIVITY_RECEIPT_EVIDENCE_CONSISTENCY / make receipt wording and transaction evidence consistent with completed and closed order states',
 canonicalCriterion:'E4 unified notification/evidence/support centre and understandable status on monetary paths',
 result:'REPRODUCED_REMAINING_PREREQUISITE',sourcePath,sourceSha256:crypto.createHash('sha256').update(source).digest('hex'),
 method:'AST-extracted real API serialization over synthetic repository rows, then exact shipped rendering helpers in Node VM. No real user/account/database/API access and no action/navigation/message execution.',
 backendContract:{inputs:backend.inputs,function:'relay-fastapi/main.py api_history',lines:backend.backendFunctionLines,
  receiptSemantics:'receipt is sent or stored whenever a persisted receipt exists, independently of order status. Completed and closed orders may legitimately retain it.',
  linkBoundary:'tx_url is constructed by core.txid.explorer_url from normalized hashes and fixed HTTPS explorers; new session tokens use secrets.token_urlsafe(24). Raw client interpolation alone did not establish production injection reachability.'},
 observedBehavior:'Receipt wording is chosen before and independently of final order status. Completed orders with stored receipts still promise that a receipt status will appear; cancelled orders can show the same future-oriented promise. A sent order with a sent receipt shows receipt-submission wording and a transaction action, while the dedicated transaction-evidence explanation is suppressed by the receipt branch.',
 reproduction:results,
 impact:'The activity centre mixes historical receipt facts/future receipt promises with an already final order outcome, making the evidence timeline less clear.',
 boundedImplementation:'Render receipt wording by lifecycle state, distinguish historical file/receipt facts from current review, retain explicit available transaction evidence independently of receipt metadata, and verify pending/paid/completed/closed cases with valid synthetic backend response shapes.',
 currentSliceDisposition:'Observed separately; not implemented during ACTIVITY_REFRESH_DEADLINE. No further timeout variants proposed.',
 limitations:['This is a reproduced UI/content inconsistency with legitimate backend response shapes, not a claim that backend status or transaction links are forged.','The past-tense phrase Чек передан на проверку can remain historically true; the precise issue is missing lifecycle context, persistent future-oriented wording and suppressed explicit transaction evidence explanation.','No real customer incidence or human misunderstanding was measured, and no E4 gate closure or earlier-stage advance is implied.']};
fs.writeFileSync(out+'/next-prerequisite.json',JSON.stringify(report,null,2)+'\n');
console.log(JSON.stringify({result:report.result,sourceSha256:report.sourceSha256,next:report.nextCanonicalItem,reproduction:results},null,2));
