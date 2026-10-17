import test from 'node:test';
import assert from 'node:assert/strict';
import http from 'node:http';
import {createPodAuthorityHandler} from './authority-handler.mjs';
const authKey='a'.repeat(32),signingKey='s'.repeat(32);
const snapshot=id=>({job:{id,business_id:'b',account_id:'a',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
 readiness:{businesses:[{id:'b',content_production_ready:true,max_mode:'PRELAUNCH'}]},
 approval:{job_id:id,business_id:'b',account_id:'a',platform:'kdp',revoked:false,production_permission:true,
  publication_permission:false,expires_at_ms:Date.now()+60000,evidence_event_id:'fixture'}});
async function serve(t,options){
 const server=http.createServer(createPodAuthorityHandler({authKey,signingKey,...options}));
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 t.after(async()=>{server.closeAllConnections();await new Promise(r=>server.close(r));});
 return signal=>fetch('http://127.0.0.1:'+server.address().port,{method:'POST',signal,
  headers:{authorization:'Bearer '+authKey,'content-type':'application/json'},body:JSON.stringify({job_id:'job'})});
}
test('authority validates lookup deadline and clock before serving',()=>{
 for(const snapshotTimeoutMs of [0,-1,1.5,Infinity,'50',10001])assert.throws(()=>createPodAuthorityHandler({
  authKey,signingKey,loadSnapshot:async()=>{},snapshotTimeoutMs}),/AUTHORITY_CONFIG_INVALID/);
 assert.throws(()=>createPodAuthorityHandler({authKey,signingKey,loadSnapshot:async()=>{},clock:0}),/AUTHORITY_CONFIG_INVALID/);
});
test('lookup timeout aborts work and late valid snapshots cannot issue grants',async t=>{
 let finish,lookupSignal,clockCalls=0;
 const pending=new Promise(resolve=>finish=resolve);t.after(()=>finish(snapshot('job')));
 const post=await serve(t,{snapshotTimeoutMs:30,clock:()=>{clockCalls++;return Date.now();},
  loadSnapshot:(_id,{signal}={})=>{lookupSignal=signal;return pending;}});
 const response=await post(AbortSignal.timeout(1000));assert.equal(response.status,409);
 assert.deepEqual(await response.json(),{error:'GRANT_BLOCKED'});
 assert.equal(lookupSignal.aborted,true);assert.equal(clockCalls,0);
 finish(snapshot('job'));await new Promise(r=>setImmediate(r));assert.equal(clockCalls,0);
});
test('client disconnect cancels lookup without issuing a grant',async t=>{
 let entered,finish,lookupSignal,clockCalls=0;
 const started=new Promise(resolve=>entered=resolve),pending=new Promise(resolve=>finish=resolve);
 t.after(()=>finish(snapshot('job')));
 const post=await serve(t,{snapshotTimeoutMs:1000,clock:()=>{clockCalls++;return Date.now();},
  loadSnapshot:(_id,{signal}={})=>{lookupSignal=signal;entered();return pending;}});
 const controller=new AbortController(),request=post(controller.signal);const rejected=assert.rejects(request,e=>e.name==='AbortError');
 await started;controller.abort();await rejected;
 assert.ok(lookupSignal,'loader receives cancellation signal');
 if(!lookupSignal.aborted)await new Promise((resolve,reject)=>{
  const timer=setTimeout(()=>reject(Error('DISCONNECT_NOT_PROPAGATED')),500);
  lookupSignal.addEventListener('abort',()=>{clearTimeout(timer);resolve();},{once:true});
 });
 finish(snapshot('job'));await new Promise(r=>setImmediate(r));assert.equal(clockCalls,0);
});
test('nonfinite authority clock cannot sign a grant',async t=>{
 const post=await serve(t,{clock:()=>NaN,loadSnapshot:async id=>snapshot(id)});
 const response=await post();assert.equal(response.status,409);assert.deepEqual(await response.json(),{error:'GRANT_BLOCKED'});
});
test('elapsed lookup deadline rejects results even before its timer callback runs',async t=>{
 let clockCalls=0,lookupSignal;
 const post=await serve(t,{snapshotTimeoutMs:10,clock:()=>{clockCalls++;return Date.now();},loadSnapshot:(id,{signal})=>{
  lookupSignal=signal;Atomics.wait(new Int32Array(new SharedArrayBuffer(4)),0,0,30);return snapshot(id);
 }});
 const response=await post();assert.equal(response.status,409);
 assert.equal(lookupSignal.aborted,true);assert.equal(clockCalls,0);
});
test('snapshot failure is redacted and following lookup can succeed',async t=>{
 let calls=0;
 const post=await serve(t,{loadSnapshot:async id=>{if(++calls===1)throw Error('private database connection');return snapshot(id);}});
 const failed=await post();assert.equal(failed.status,409);assert.deepEqual(await failed.json(),{error:'GRANT_BLOCKED'});
 const success=await post();assert.equal(success.status,200);assert.equal(JSON.parse((await success.json()).payload).publication_permission,false);
});
test('HTTP authority reloads approval and rejects injected authority data',async()=>{
 let revoked=false,loads=0;
 const handler=createPodAuthorityHandler({authKey,signingKey,loadSnapshot:async id=>{loads++;return {
  job:{id,business_id:'b',account_id:'a',platform:'kdp',destination_platform:'kdp',mode:'PRELAUNCH'},
  readiness:{businesses:[{id:'b',content_production_ready:true,max_mode:'PRELAUNCH',launch_content_allowed:false}]},
  approval:{job_id:id,business_id:'b',account_id:'a',platform:'kdp',revoked,production_permission:true,publication_permission:false,expires_at_ms:Date.now()+60000,evidence_event_id:'approval'}
 };}});
 const server=http.createServer(handler);await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const url='http://127.0.0.1:'+server.address().port;
 const post=(body,auth='Bearer '+authKey)=>fetch(url,{method:'POST',headers:{authorization:auth,'content-type':'application/json'},body:JSON.stringify(body)});
 try{
  let r=await post({job_id:'job'});assert.equal(r.status,200);assert.equal(JSON.parse((await r.json()).payload).publication_permission,false);
  revoked=true;r=await post({job_id:'job'});assert.equal(r.status,409);assert.equal(loads,2);
  assert.equal((await post({job_id:'job',approval:{revoked:false}})).status,409);assert.equal(loads,2);
  assert.equal((await post({job_id:'job'},'Bearer wrong')).status,401);assert.equal(loads,2);
 }finally{server.closeAllConnections();await new Promise(r=>server.close(r));}
});
