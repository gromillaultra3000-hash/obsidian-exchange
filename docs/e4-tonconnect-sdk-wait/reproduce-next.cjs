'use strict';
// This intentionally reproduces the remaining fetch/body deadline defect.
const assert=require('node:assert/strict');
const {harness,flush}=require('./acceptance.cjs');
(async()=>{
  const cases=[];
  for(const stage of ['fetch','body']) {
    const h=harness('immediate',{stallPayload:stage});let settled=false;
    h.connect().then(()=>{settled=true;});await flush();
    h.advance(3600000);await flush();await h.connect();
    assert.equal(h.stats().payloadAborted,true);
    assert.equal(settled,false);assert.equal(h.nodes['tc-connect'].disabled,true);
    assert.equal(h.get('tcPreparation !== null'),true);assert.equal(h.stats().payloads,1);
    assert.equal(h.timers.size,0);
    cases.push({stage,simulatedElapsedMs:3600000,abortSignalled:true,preparationPending:true,connectButtonDisabled:true,activeDeadlineTimers:0,newRequestsAfterRetry:0});
  }
  console.log(JSON.stringify({criterion:'TONCONNECT_PAYLOAD_WAIT_RECOVERY',result:'REPRODUCED',cases,realNetworkCalls:0,walletSignatures:0,moneyWrites:0}));
})().catch(error=>{console.error(error);process.exitCode=1;});
