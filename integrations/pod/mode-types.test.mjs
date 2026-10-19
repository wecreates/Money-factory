import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {issuePodGrant} from './readiness-grant.mjs';
import {createPodAuthorityHandler} from './authority-handler.mjs';
const key='s'.repeat(32),authKey='a'.repeat(32),now=1700000000000;
function fixture(){return {key,now,
 job:{id:'job',business_id:'b',account_id:'a',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
 readiness:{businesses:[{id:'b',content_production_ready:true,max_mode:'LAUNCH',launch_content_allowed:false}]},
 approval:{job_id:'job',business_id:'b',account_id:'a',platform:'kdp',production_permission:true,publication_permission:false,
  revoked:false,expires_at_ms:now+60000,evidence_event_id:'fixture-only'}};}
const invalidModes=[['LAUNCH'],['PRELAUNCH'],['RESEARCH'],new String('LAUNCH'),{toString:()=> 'LAUNCH'},null,0,true,'launch','LAUNCH\n'];
test('coercible job modes cannot bypass launch permission and economics checks',()=>{
 for(const mode of invalidModes){const s=fixture();s.job.mode=mode;
  assert.throws(()=>issuePodGrant(s),/READINESS_BLOCKED/);}
});
test('readiness ceilings must be exact mode strings',()=>{
 for(const mode of invalidModes){const s=fixture();s.readiness.businesses[0].max_mode=mode;
  s.job.mode='RESEARCH';assert.throws(()=>issuePodGrant(s),/READINESS_BLOCKED/);}
});
test('exact string modes preserve the readiness ceiling and launch safeguards',()=>{
 const modes=['RESEARCH','PRELAUNCH','LAUNCH'];
 for(let ceiling=0;ceiling<modes.length;ceiling++)for(let requested=0;requested<modes.length;requested++){
  const s=fixture();s.readiness.businesses[0].max_mode=modes[ceiling];s.job.mode=modes[requested];
  if(requested>ceiling)assert.throws(()=>issuePodGrant(s),/READINESS_BLOCKED/);
  else if(s.job.mode==='LAUNCH')assert.throws(()=>issuePodGrant(s),/LAUNCH_BLOCKED/);
  else{const grant=JSON.parse(issuePodGrant(s).payload);assert.equal(grant.max_mode,modes[ceiling]);assert.equal(grant.publication_permission,false);}
 }
});
test('HTTP authority blocks malformed modes in server snapshots without signing them',async t=>{
 let badCeiling=false;
 const server=http.createServer(createPodAuthorityHandler({authKey,signingKey:key,clock:()=>now,loadSnapshot:async()=>{
  const s=fixture();if(badCeiling)s.readiness.businesses[0].max_mode=['LAUNCH'];else s.job.mode=['LAUNCH'];return s;
 }}));
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));});
 for(const value of [false,true]){badCeiling=value;
  const response=await fetch('http://127.0.0.1:'+server.address().port,{method:'POST',
   headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},body:'{"job_id":"job"}'});
  assert.equal(response.status,409);assert.deepEqual(await response.json(),{error:'GRANT_BLOCKED'});
 }
});
